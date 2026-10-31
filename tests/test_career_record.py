"""The career record checker (ADR-0004; format in docs/career-record/FORMAT.md)."""
import tempfile
import unittest
from pathlib import Path

from jobweaver import career_record

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'career_record.example.yaml'


class CareerRecordCheckTest(unittest.TestCase):
    def setUp(self):
        self.text = EXAMPLE.read_text(encoding='utf-8')
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def problems(self, old=None, new=None, text=None):
        if text is None:
            text = self.text
            if old is not None:
                self.assertEqual(text.count(old), 1, old)
                text = text.replace(old, new)
        path = Path(self.temp.name, 'record.yaml')
        path.write_text(text, encoding='utf-8')
        return [p for p in career_record.check(path) if not p.warning]

    def assertProblem(self, old, new, fragment, line=None):
        problems = self.problems(old, new)
        found = [p for p in problems if fragment in p.message]
        self.assertTrue(found, [p.message for p in problems])
        if line is not None:
            self.assertEqual(found[0].line, line, found[0])

    def test_example_is_valid_and_summarised(self):
        self.assertEqual(self.problems(), [])
        summary = career_record.summary(EXAMPLE)
        self.assertIn('4 entries, 8 claims (4 on every CV, 0 on some;', summary)
        self.assertIn('1 stretch,', summary)

    def test_german_cv_warning_is_not_an_error(self):
        warnings = [p for p in career_record.check(EXAMPLE) if p.warning]
        self.assertTrue(any('German' in p.message for p in warnings))

    def test_yaml_syntax_error_names_the_line(self):
        problems = self.problems(text='format: 1\nname: [unclosed\n')
        self.assertEqual(len(problems), 1)
        self.assertIn('YAML syntax error', problems[0].message)
        self.assertGreaterEqual(problems[0].line, 2)

    def test_structure(self):
        self.assertProblem('format: 1\n', 'format: 2\n', '"format" must be 1', line=3)
        self.assertProblem('    organisation: University of Graz\n', '    organization: University of Graz\n',
                           'unknown field "organization"')
        self.assertProblem("        evidence: Degree certificate.\n", "        evidence: ''\n", 'must be non-empty text')
        self.assertProblem('  - id: msc\n', '  - id: MSc\n', 'lowercase letters')
        self.assertProblem('      - id: msc-degree\n', '      - id: weather-lab-pipeline\n', 'used twice (first on line')
        self.assertProblem('    type: education\n', '    type: school\n', 'entry type must be one of')
        self.assertProblem('        ownership: adapted\n', '        ownership: borrowed\n', 'ownership must be one of')

    def test_cut_claims(self):
        self.assertProblem('        reason: The frontend', '        evidence: The frontend', 'needs a "reason"')
        self.assertProblem('        ownership: cut\n', '        ownership: cut\n        cv: true\n', 'never be on the CV')

    def test_every_other_claim_needs_evidence(self):
        self.assertProblem('        evidence: Thesis acknowledgements.\n', '', 'needs "evidence"')

    def test_basics_stay_off_the_cv_and_unstretched(self):
        self.assertProblem('        ownership: basics\n', '        ownership: basics\n        cv: true\n',
                           'only on request, never on the CV')

    def test_adapted_and_steered_wording(self):
        self.assertProblem('Adapted an existing quality-control tool', 'Improved an existing quality-control tool',
                           'must say "adapted"')
        self.assertProblem('Specified and operate an AI-built job-search tool',
                           'Developed and operate an AI-built job-search tool', 'worded as authorship ("Developed")')
        self.assertProblem('Specified and operate an AI-built job-search tool', 'Use an AI-built job-search tool',
                           'must say "specified" or "operate"')

    def test_stretch_rules(self):
        stretch = 'Built the group\'s data preparation pipeline for 40 TB of climate model output.'
        self.assertProblem(stretch, 'Built the group\'s pipeline for 400 TB of climate model output.',
                           'may not add numbers: 400')
        self.assertProblem(stretch, 'Built the group\'s Kubernetes pipeline for 40 TB of model output.',
                           'may not name tools the claim does not: Kubernetes')
        self.assertProblem("            defence: It was a set of scripts", "            note: It was a set of scripts",
                           'missing "defence"')
        extra = ('          - text: Ran the group\'s data preparation for 40 TB.\n            defence: Same scripts.\n'
                 '          - text: Owned data preparation for 40 TB.\n            defence: Same scripts.\n')
        self.assertProblem('            defence: It was a set of scripts run in sequence, not a framework; I wrote all of them.\n',
                           '            defence: It was a set of scripts run in sequence, not a framework; I wrote all of them.\n' + extra,
                           'at most 2 stretches')

    def test_angles_and_forbidden_phrases(self):
        self.assertProblem('      data-engineering: Daily work', '      data-science: Daily work', 'unknown role family "data-science"')
        self.assertProblem('Basic unit tests with pytest', 'Basic test automation with pytest', 'forbidden phrase "test automation"')
        # a description may say what an entry is not
        self.assertEqual(self.problems('Small open-source package for return-period',
                                       'Small open-source package, not test automation, for return-period'), [])
        # an excluded claim may name what is excluded
        self.assertEqual(self.problems('React frontend development.', 'React frontend, test automation.'), [])

    def test_cv_may_name_role_families(self):
        self.assertEqual(self.problems('        ownership: steered\n        cv: false\n',
                                       '        ownership: steered\n        cv: [data-engineering]\n'), [])
        self.assertProblem('        ownership: steered\n        cv: false\n', '        ownership: steered\n        cv: [ai]\n',
                           'unknown role families: ai')
        self.assertProblem('        ownership: basics\n', '        ownership: basics\n        cv: [data-engineering]\n',
                           'never on the CV')

    def test_links_are_web_addresses(self):
        self.assertProblem('      - https://example.org/rainfall-stats\n', '      - example.org/rainfall-stats\n',
                           'list of web addresses')

    def test_german_wordings_keep_numbers_tools_and_kind(self):
        self.assertProblem('        de: Python-Skripte geschrieben, die 40 TB', '        de: Python-Skripte geschrieben, die 400 TB',
                           'same numbers as the English')
        self.assertProblem('        de: Python-Skripte geschrieben, die 40 TB Modelldaten in auswertbare NetCDF-Dateien umwandeln.',
                           '        de: Python-Skripte mit Kubernetes geschrieben, die 40 TB Modelldaten umwandeln.',
                           'same tools as the English')
        self.assertProblem('        evidence: Commit history of the group',
                           '        de: Ein Werkzeug verbessert, das fehlerhafte Läufe markiert.\n        evidence: Commit history of the group',
                           'must say "angepasst"')
        self.assertProblem('    angles:\n      research-software: A released package',
                           '    angles_de:\n      data-engineering: Ein Paket.\n    angles:\n      research-software: A released package',
                           'German angle for "data-engineering" without an English angle')

    def test_cli_exit_codes(self):
        self.assertEqual(career_record.main(['check', str(EXAMPLE)]), 0)
        path = Path(self.temp.name, 'bad.yaml')
        path.write_text('format: 1\n', encoding='utf-8')
        self.assertEqual(career_record.main(['check', str(path)]), 1)
        self.assertEqual(career_record.main([]), 2)
        self.assertEqual(career_record.main(['text', str(EXAMPLE)]), 0)


if __name__ == '__main__':
    unittest.main()
