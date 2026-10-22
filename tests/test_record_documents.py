"""Documents from a career record (ADR-0004, build step 4), with the fictional example user."""
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import reviewed_documents as documents
import user_assets

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'career_record.example.yaml'
FILLER = ' The work required careful checks of every result before anyone else relied on it.'
JOB = {'title': 'Research Software Engineer', 'company': 'Climate Lab',
       'description': 'We need research software for climate data pipelines.'}


class RecordDocumentsTest(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        patcher = patch.multiple(user_assets, BASE_DIR=temp.name, PROFILES_DIR=str(Path(temp.name, 'profiles')))
        patcher.start()
        self.addCleanup(patcher.stop)
        self.profile = Path(user_assets.user_profile_dir('alex'))
        self.profile.mkdir(parents=True)
        shutil.copy(EXAMPLE, self.profile / 'career_record.yaml')
        self.settings({})
        self.labels, self.letter_prompts = [], []
        self.plan = {'plan': [
            {'claim_id': 'weather-lab-pipeline', 'need': 'climate data pipelines', 'wording': 'stretch-1'},
            {'claim_id': 'weather-lab-checker', 'need': 'reliable data', 'wording': 'plain'},
            {'claim_id': 'rainfall-author', 'need': 'research software', 'wording': 'plain'}]}

    def settings(self, values):
        (self.profile / 'scraper_config.json').write_text(json.dumps({'letter_verifier_model': 'mock-verifier', **values}))

    def letter(self, extra='', cite_unplanned=False):
        return {'salutation': 'Dear Hiring Team,', 'paragraphs': [
            {'text': 'Your team prepares climate data for research. For four years I turned raw model output into '
                     'data a research group could rely on, and learned where such data goes wrong.' + FILLER,
             'fact_ids': ['weather-lab.angle']},
            {'text': 'For the group, I built the pipeline that prepared 40 TB of climate model output for analysis.' + FILLER * 2
                     + ' I also adapted an existing quality-control tool so that corrupted model runs are flagged before anyone analyses them.'
                     + extra, 'fact_ids': ['weather-lab-pipeline', 'weather-lab-checker']},
            {'text': 'rainfall-stats, the package I lead as main developer, has had three releases on PyPI.' + FILLER * 2,
             'fact_ids': ['rainfall-author'] + (['weather-lab-teaching'] if cite_unplanned else [])},
            {'text': 'I live in Graz and would welcome a conversation about your work.' + FILLER,
             'fact_ids': ['fact.location']}]}

    def model(self, letters=None, plan=None, verdict='supported'):
        letters = list(letters or [self.letter()])

        def run(prompt, **kwargs):
            label = kwargs.get('label')
            self.labels.append(label)
            if label == 'Letter plan':
                return json.dumps(plan or self.plan)
            if label == 'Letter verification':
                return json.dumps({'verdicts': [{'n': n, 'verdict': verdict if n == 1 else 'supported', 'note': 'test'}
                                                for n in range(1, 40)]})
            self.letter_prompts.append(prompt)
            return json.dumps(letters.pop(0) if len(letters) > 1 else letters[0])
        return run

    def generate(self, kind, job=JOB, profile='research', **kwargs):
        return documents.generate(job, None, 'alex', 'latex', kind, profile, 'mock', kwargs.pop('run', None) or self.model(), **kwargs)

    def test_role_family_from_terms_override_or_first(self):
        record, _ = documents.career_record_for('alex')
        self.assertEqual(documents.record_family(record, JOB), 'research-software')
        self.assertEqual(documents.record_family(record, {'title': 'Data Engineer', 'description': 'ETL pipeline'}),
                         'data-engineering')
        self.assertEqual(documents.record_family(record, {'title': 'Baker'}), 'research-software')
        # whole words only: "etl" must not match inside "kettle"
        self.assertEqual(documents.record_family(record, {'title': 'Kettle maker', 'description': 'kettles'}), 'research-software')
        self.assertEqual(documents.record_family(record, JOB, 'data-engineering'), 'data-engineering')

    def test_cv_comes_from_the_record_without_a_model_call(self):
        def no_call(*a, **k):
            raise AssertionError('no model call expected')
        source = self.generate('cv', job={'title': 'Data Engineer', 'description': 'ETL pipeline'}, run=no_call)
        self.assertIn('Python Developer | Data Pipelines', source)
        self.assertIn('Alex Example', source)
        with self.assertRaisesRegex(ValueError, 'career record'):
            documents.grounded_edit(source, 'Remove a bullet', 'alex', 'mock', no_call)

    def test_letter_plans_from_the_record_and_is_verified(self):
        notes = []
        source = self.generate('letter', notes=notes)
        self.assertEqual(self.labels, ['Letter plan', 'Grounded letter', 'Letter verification'])
        prompt = self.letter_prompts[0]
        self.assertIn("Built the group's data preparation pipeline", prompt)          # the approved stretch
        self.assertIn('Four years of turning model output', prompt)                  # the angle
        self.assertNotIn('Basic unit tests', prompt)                                 # basics are not citable
        self.assertNotIn('Supervised two bachelor theses', prompt)                   # not planned
        self.assertIn('Alex Example', source)
        self.assertIn('Research Software Engineer | Climate Data', source)          # the family's headline
        self.assertTrue(any('(approved stretch)' in n for n in notes))

    def test_plan_rules(self):
        store = documents.record_store(*reversed(documents.career_record_for('alex')[::-1]), 'research-software')
        _, problems = documents.check_record_plan({'plan': [
            {'claim_id': 'rainfall-tests', 'need': 'testing', 'wording': 'plain'},
            {'claim_id': 'msc-degree', 'need': 'degree', 'wording': 'stretch-1'}]}, store, 2)
        text = ' '.join(problems)
        self.assertIn('basics and excluded claims cannot be used', text)
        self.assertIn('has no wording "stretch-1"', text)
        self.assertIn('at least two claims from work entries', text)
        _, problems = documents.check_record_plan(self.plan, store, 0)
        self.assertIn('Use at most 0 stretches, not 1', problems)

    def test_stretch_cap_comes_from_settings(self):
        self.settings({'max_stretches_per_letter': 0})
        with self.assertRaisesRegex(ValueError, 'Use at most 0 stretches'):
            self.generate('letter')

    def test_letter_may_cite_only_planned_claims(self):
        notes = []
        self.generate('letter', run=self.model(letters=[self.letter(cite_unplanned=True), self.letter()]), notes=notes)
        self.assertTrue(any('Unknown fact IDs: weather-lab-teaching' in n for n in notes), notes)  # never offered to the writer

    GERMAN = dict(JOB, description='Wir suchen eine Person für die Entwicklung der Software und die Auswertung der Daten im Team.')

    def add_german(self):
        path = self.profile / 'career_record.yaml'
        text = path.read_text()
        for english, german in (
                ('        text: Adapted an existing quality-control tool to flag corrupted model runs before analysis.\n',
                 '        text: Adapted an existing quality-control tool to flag corrupted model runs before analysis.\n'
                 '        de: Ein bestehendes Qualitätskontroll-Werkzeug angepasst, das fehlerhafte Modellläufe vor der Analyse markiert.\n'),
                ('        text: Main developer of rainfall-stats, released on PyPI with three releases.\n',
                 '        text: Main developer of rainfall-stats, released on PyPI with three releases.\n'
                 '        de: Hauptentwickler von rainfall-stats, auf PyPI mit drei Versionen veröffentlicht.\n'),
                ('            defence: It was a set of scripts',
                 '            de: Die Datenaufbereitung der Gruppe für 40 TB Klimamodelldaten aufgebaut.\n            defence: It was a set of scripts'),
                ('      data-engineering: Daily work with large gridded datasets',
                 '      data-engineering: Daily work with large gridded datasets')):
            self.assertEqual(text.count(english), 1, english)
            text = text.replace(english, german)
        text = text.replace('    claims:\n      - id: weather-lab-pipeline',
                            '    angles_de:\n      research-software: Vier Jahre Modelldaten für eine Forschungsgruppe aufbereitet.\n'
                            '    claims:\n      - id: weather-lab-pipeline')
        path.write_text(text)

    def test_english_is_the_default_even_for_german_postings(self):
        source = self.generate('letter', job=self.GERMAN)
        self.assertIn('Kind regards', source)

    def test_german_letter_needs_german_wordings(self):
        with self.assertRaisesRegex(ValueError, 'approved German wording'):
            self.generate('letter', job=self.GERMAN, language='de')   # rainfall-author has no German yet

    def test_german_letter_from_german_wordings(self):
        self.add_german()
        source = self.generate('letter', job=self.GERMAN, language='de')
        self.assertIn('Mit freundlichen Grüßen', source)
        prompt = self.letter_prompts[0]
        self.assertIn('Hauptentwickler von rainfall-stats', prompt)
        self.assertIn('Vier Jahre Modelldaten', prompt)
        self.assertNotIn('Supervised two bachelor theses', prompt)

    def test_german_cv_lists_what_is_missing(self):
        with self.assertRaisesRegex(ValueError, 'German CV needs German wording for: .*claim weather-lab-checker'):
            self.generate('cv', language='de')
        with self.assertRaisesRegex(ValueError, 'Unsupported document language'):
            self.generate('cv', language='fr')

    def test_cv_wording_is_rejected_in_letters(self):
        fact = 'Main developer of rainfall-stats, an open-source package released on PyPI with three releases.'
        copied = documents._copy_problems('I am the main developer of rainfall-stats, an open-source package released on PyPI with three releases.', [fact], 'P2')
        self.assertTrue(any('word for word' in p for p in copied), copied)
        self.assertEqual(documents._copy_problems('rainfall-stats, the package I lead, has had three releases on PyPI.', [fact], 'P2'), [])
        formatted = documents._copy_problems('I used databases: MongoDB, SQLite and more (see polflow).', [], 'P3')
        self.assertEqual(len(formatted), 2, formatted)

    def test_led_to_is_not_leadership(self):
        self.assertEqual(documents._strength_problems('Tracing the failure led to a fix upstream.', '', '', 'P1'), [])
        self.assertTrue(documents._strength_problems('I led a team of three.', '', '', 'P1'))

    def test_a_retry_revises_the_previous_letter(self):
        bad = self.letter(' We also built backend services together.')
        self.settings({'max_stretches_per_letter': 2})
        (self.profile / 'career_record.yaml').write_text(
            (self.profile / 'career_record.yaml').read_text().replace('  - architected\n', '  - architected\n  - backend services\n'))
        self.generate('letter', run=self.model(letters=[bad, self.letter()]))
        self.assertNotIn('Your previous letter:', self.letter_prompts[0])
        self.assertIn('Your previous letter:', self.letter_prompts[1])
        self.assertIn('backend services together', self.letter_prompts[1])
        self.assertIn('Fix exactly these problems', self.letter_prompts[1])

    def test_style_is_reported_never_retried(self):
        copying = self.letter(" I built the group's data preparation pipeline for 40 TB of climate model output.")
        notes = []
        self.generate('letter', run=self.model(letters=[copying]), notes=notes)
        self.assertEqual(self.labels.count('Grounded letter'), 1)
        self.assertTrue(any(n.startswith('style') and 'word for word' in n for n in notes), notes)

    def test_strength_is_left_to_the_verifier_for_record_letters(self):
        notes = []
        self.generate('letter', run=self.model(letters=[self.letter(' Your production infrastructure sounds interesting.')]), notes=notes)
        self.assertEqual(self.labels.count('Grounded letter'), 1, notes)

    def test_scoring_reads_the_record(self):
        text = user_assets.load_effective_cv('alex')
        self.assertIn('Wrote Python scripts that convert 40 TB', text)
        self.assertIn('[adapted from existing code]', text)
        self.assertIn('[AI-built to my specification]', text)
        self.assertIn('Basic unit tests with pytest for the package\'s core functions. [basic knowledge only]', text)
        self.assertNotIn('React frontend', text)           # excluded claims never reach scoring
        self.assertNotIn('Ask 10 %', text)                 # policies are not CV text
        self.assertIn('Return-period statistics', text.replace('return-period', 'Return-period'))

    def add_personal_context(self):
        path = self.profile / 'career_record.yaml'
        path.write_text(path.read_text().replace('applicant_facts:\n', '''applicant_facts:
  - id: personal-debugging
    text: I enjoy finding the cause of an unexpected failure.
    de: Ich finde gerne die Ursache eines unerwarteten Fehlers.
  - id: personal-baking
    text: I enjoy baking bread.
  - id: school-detail
    text: An unrelated form answer that must not reach letter writing.
'''))

    def test_personal_context_reaches_letters_but_not_cv_or_scoring(self):
        import career_cv
        import career_record
        before, _ = documents.career_record_for('alex')
        cv = career_cv.render(before, 'research-software')
        scoring = career_record.scoring_text(before)
        self.add_personal_context()
        after, _ = documents.career_record_for('alex')
        self.assertEqual(career_cv.render(after, 'research-software'), cv)
        self.assertEqual(career_record.scoring_text(after), scoring)
        letter = self.letter()
        letter['paragraphs'][0]['text'] += ' I enjoy finding the cause of an unexpected failure.'
        letter['paragraphs'][0]['fact_ids'].append('fact.personal-debugging')
        self.generate('letter', run=self.model(letters=[letter]))
        self.assertEqual(self.labels.count('Grounded letter'), 1)
        self.assertIn('fact.personal-debugging', self.letter_prompts[0])
        self.assertIn('I enjoy baking bread.', self.letter_prompts[0])
        self.assertNotIn('An unrelated form answer', self.letter_prompts[0])

    def test_personal_context_is_optional_and_does_not_replace_work_evidence(self):
        self.add_personal_context()
        self.generate('letter')  # a letter with no personal reference still passes
        record, text = documents.career_record_for('alex')
        store = documents.record_store(record, text, 'research-software')
        _, problems = documents.check_record_plan({'plan': [
            {'claim_id': 'fact.personal-debugging', 'need': 'debugging', 'wording': 'plain'},
            {'claim_id': 'fact.personal-baking', 'need': 'company baking club', 'wording': 'plain'},
            {'claim_id': 'rainfall-author', 'need': 'research software', 'wording': 'plain'}]}, store, 2)
        self.assertTrue(any('at least two claims from work entries' in p for p in problems))

    def test_only_one_distinct_personal_reference_per_letter(self):
        self.add_personal_context()
        letter = self.letter()
        letter['paragraphs'][0]['text'] += ' I enjoy baking bread and finding the cause of an unexpected failure.'
        letter['paragraphs'][0]['fact_ids'] += ['fact.personal-debugging', 'fact.personal-baking']
        notes = []
        self.generate('letter', run=self.model(letters=[letter, self.letter()]), notes=notes)
        self.assertEqual(self.labels.count('Grounded letter'), 2)
        self.assertTrue(any('at most one personal-context fact' in n for n in notes), notes)

    def test_german_personal_context_uses_only_approved_translations(self):
        self.add_german()
        self.add_personal_context()
        self.generate('letter', job=self.GERMAN, language='de')
        prompt = self.letter_prompts[0]
        self.assertIn('Ich finde gerne die Ursache', prompt)
        self.assertNotIn('I enjoy finding the cause', prompt)
        self.assertNotIn('fact.personal-baking', prompt)
        self.assertNotIn('I enjoy baking bread.', prompt)

    def test_web_cv_editor_is_read_only_for_record_users(self):
        import server
        from fastapi import HTTPException
        shown = server.get_cv(user={'username': 'alex'})
        self.assertTrue(shown['read_only'])
        self.assertIn('Alex Example', shown['content'])
        with self.assertRaises(HTTPException) as raised:
            server.save_cv(server.CvTextPayload(content='x'), user={'username': 'alex'})
        self.assertEqual(raised.exception.status_code, 409)

    def test_record_with_errors_stops_generation(self):
        path = self.profile / 'career_record.yaml'
        path.write_text(path.read_text().replace('format: 1', 'format: 2'))
        with self.assertRaisesRegex(ValueError, 'career record .* has errors'):
            self.generate('cv')


if __name__ == '__main__':
    unittest.main()
