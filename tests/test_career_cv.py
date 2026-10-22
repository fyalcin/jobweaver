"""Rendering a CV from a career record (career_cv.py, build step 3)."""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import career_cv
import career_record

EXAMPLE = Path(__file__).resolve().parents[1] / 'examples' / 'career_record.example.yaml'


class CareerCvTest(unittest.TestCase):
    def setUp(self):
        self.record, _ = career_record.load(EXAMPLE)

    def test_shows_cv_claims_in_record_order_and_nothing_else(self):
        source = career_cv.render(self.record, 'research-software')
        self.assertIn(r'Research Software Engineer | Climate Data \& Python', source)
        self.assertLess(source.index('40 TB of model output'), source.index('quality-control tool'))
        for hidden in ('Supervised two bachelor theses',  # letter-only
                       'Basic unit tests',                 # basics
                       'React frontend',                   # cut
                       'Specified and operate',            # steered, not on the CV
                       'Built the group',                  # a stretch is never on the CV
                       'Ask 10 %'):                        # an application policy
            self.assertNotIn(hidden, source)
        self.assertIn(r'\href{https://example.org/rainfall-stats}{example.org/rainfall-stats}', source)

    def test_only_the_headline_and_family_claims_differ(self):
        record = dict(self.record)
        entries = [dict(e, claims=[dict(c) for c in e['claims']]) for e in record['entries']]
        steered = next(c for e in entries for c in e['claims'] if c['ownership'] == 'steered')
        steered['cv'] = ['data-engineering']
        record['entries'] = entries
        research = career_cv.render(record, 'research-software')
        data = career_cv.render(record, 'data-engineering')
        self.assertNotIn('Specified and operate', research)
        self.assertIn('Specified and operate', data)
        self.assertIn('Python Developer | Data Pipelines', data)
        with self.assertRaisesRegex(ValueError, 'unknown role family'):
            career_cv.render(record, 'astronaut')

    def test_escaping_and_bold(self):
        self.assertEqual(career_cv.tex('**Rot-Weiß-Rot** 10 % & #1_a'), r'\textbf{Rot-Weiß-Rot} 10 \% \& \#1\_a')

    def test_cli_refuses_a_record_with_errors(self):
        with tempfile.TemporaryDirectory() as temp:
            bad = Path(temp, 'bad.yaml')
            bad.write_text('format: 1\n', encoding='utf-8')
            self.assertEqual(career_cv.main([str(bad), '--family', 'x']), 1)
            out = Path(temp, 'cv.tex')
            self.assertEqual(career_cv.main([str(EXAMPLE), '--family', 'research-software', '--out', str(out)]), 0)
            self.assertTrue(out.read_text(encoding='utf-8').startswith('% Layout for CVs'))

    @unittest.skipUnless(shutil.which('pdflatex') and shutil.which('pdfinfo'), 'pdflatex/pdfinfo missing')
    def test_example_compiles_to_two_pages(self):
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'cv.tex').write_text(career_cv.render(self.record, 'data-engineering'), encoding='utf-8')
            subprocess.run(['pdflatex', '-interaction=nonstopmode', 'cv.tex'], cwd=temp, capture_output=True, timeout=120)
            info = subprocess.run(['pdfinfo', 'cv.pdf'], cwd=temp, capture_output=True, text=True).stdout
            self.assertIn('Pages:           2', info)
            self.assertNotIn('Overfull', Path(temp, 'cv.log').read_text(errors='replace'))


if __name__ == '__main__':
    unittest.main()
