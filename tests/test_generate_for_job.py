"""Command-line document generation: one JSON object, idempotent, all-or-nothing, same reviewed pipeline."""
import contextlib
import io
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from jobweaver import db

# Point db at a throwaway SQLite file BEFORE importing anything that opens it.
_TMP = tempfile.mkdtemp(prefix="gj-cli-test-")
db.set_db_path(os.path.join(_TMP, "test.db"))

from jobweaver import daily_scraper  # noqa: E402
from jobweaver import generate_for_job  # noqa: E402
from jobweaver import reviewed_documents  # noqa: E402
from jobweaver import user_assets  # noqa: E402

CV = 'Synthetic Applicant\nEXPERIENCE\nResearch lab | 2020-2024\n- Used Python for simulations.\n- Learning SQL basics.'
FILLER = ' The work required careful checks of every result before anyone else relied on it.'


def _letter(store, extra=''):
    facts = reviewed_documents.letter_evidence(store)
    python = [key for key, value in facts.items() if 'Used Python' in value]
    lab = [key for key, value in facts.items() if 'Research lab' in value]
    return {'salutation': 'Dear Hiring Team,', 'paragraphs': [
        {'text': 'Your role combines simulation with software that colleagues depend on every day.' + FILLER, 'fact_ids': []},
        {'text': 'At the research lab I used Python for simulation and kept the workflows maintainable.' + FILLER * 3 + extra, 'fact_ids': python},
        {'text': 'Between 2020 and 2024 the research lab gave me regular practice in explaining results.' + FILLER * 3, 'fact_ids': lab},
        {'text': 'I would welcome a conversation about the problems your team is working on.' + FILLER, 'fact_ids': []}]}


def _plan(store):
    facts = reviewed_documents.letter_evidence(store)
    return {'plan': [{'fact_id': key, 'need': 'Python simulations', 'framing': value}
                     for key, value in facts.items() if 'Used Python' in value or 'Research lab' in value]}


def _all_supported():
    return {'verdicts': [{'n': n, 'verdict': 'supported', 'note': ''} for n in range(1, 40)]}


@unittest.skipUnless(shutil.which('pdflatex') and shutil.which('pdfinfo'), 'Native LaTeX/Poppler prerequisites missing')


def setUpModule():
    # Discovery imports every module first; point at this module's DB while it runs.
    db.set_db_path(os.path.join(_TMP, "test.db"))


def tearDownModule():
    db.set_db_path(os.path.join(db.DATA_DIR, "jobweaver.db"))  # The runner's disposable default.


class GenerateForJobTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        db.init_db()
        cls.name = f'clitest{id(cls) % 100000}'
        cls.user = db.create_user(cls.name, password_hash='x', display_name='CLI')

    @classmethod
    def tearDownClass(cls):
        db.delete_user(cls.user['id'])
        shutil.rmtree(_TMP, ignore_errors=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        patcher = patch.multiple(user_assets, BASE_DIR=self.temp.name, PROFILES_DIR=str(Path(self.temp.name, 'profiles')))
        patcher.start()
        self.addCleanup(patcher.stop)
        profile = Path(user_assets.user_profile_dir(self.name))
        profile.mkdir(parents=True)
        (profile / 'CV-plaintext.txt').write_text(CV)
        (profile / 'scraper_config.json').write_text(json.dumps(
            {'document_model': 'mock', 'auto_generate': {'document_engine': 'latex'}}))
        self.store = reviewed_documents.evidence(self.name, CV)
        self.model_calls = []
        self.noisy = False
        self.letters = []  # answers for letter requests, consumed in order; the last one repeats
        self.cv_answer = {'fact_ids': list(self.store['facts'])}
        patcher = patch('jobweaver.generators.run_ai_prompt', side_effect=self._model)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.job_id = 'li_9' + str(time.time_ns())[-8:]
        self.job = {'id': self.job_id, 'job_url': f'https://example.test/{self.job_id}', 'title': 'Research Software Engineer',
                    'company': 'Synthetic Co', 'description': 'Python simulations and maintainable research software.',
                    'date_scraped': '2026-10-12', 'source': 'test', 'german_level': 'none'}
        db.upsert_job(self.job, user_id=self.user['id'])
        folder = daily_scraper._job_folder(self.job)[2]
        self.output = Path(user_assets.user_outputs_dir(self.name), folder)

    def _model(self, prompt, **kwargs):
        label = kwargs.get('label', '')
        self.model_calls.append(label)
        if self.noisy:
            print('noise that must never reach stdout')
        if label.startswith('Approved evidence'):
            return json.dumps(self.cv_answer)
        if label == 'Letter plan':
            return json.dumps(_plan(self.store))
        if label == 'Letter verification':
            return json.dumps(_all_supported())
        answer = self.letters.pop(0) if len(self.letters) > 1 else self.letters[0] if self.letters else _letter(self.store)
        return answer if isinstance(answer, str) else json.dumps(answer)

    def cli(self, *extra, job=None):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = generate_for_job.main(['--user', self.name, '--job', job or self.job_id, *extra])
        lines = buffer.getvalue().splitlines()
        self.assertEqual(len(lines), 1, buffer.getvalue())
        return json.loads(lines[0]), code

    def revisions(self):
        folder = self.output / 'revisions'
        return sorted(p.name for p in folder.iterdir()) if folder.exists() else []

    # --- success -------------------------------------------------------------------------------

    def test_success_prints_one_json_object_with_paths_and_names(self):
        self.noisy = True  # library output must not reach stdout
        result, code = self.cli()
        self.assertEqual(code, 0)
        self.assertTrue(result['ok'])
        self.assertFalse(result['cached'])
        self.assertEqual(result['job_id'], self.job_id)
        for key in ('cv_pdf', 'letter_pdf'):
            path = Path(result[key])
            self.assertTrue(path.is_absolute() and path.is_file(), result[key])
            self.assertTrue(path.read_bytes().startswith(b'%PDF-'))
        self.assertEqual(result['cv_download_name'], 'Synthetic_Applicant_CV.pdf')
        self.assertEqual(result['letter_download_name'], 'Synthetic_Applicant_Cover_Letter.pdf')
        self.assertEqual(result['engine'], 'latex')
        self.assertEqual(result['model'], 'mock')
        self.assertEqual(len(result['validation']), 2)
        self.assertTrue(all('PDF parsed' in line for line in result['validation']))
        self.assertEqual(result['warnings'], [])
        self.assertEqual(result['errors'], [])
        publication = json.loads((self.output / 'publication.json').read_text())
        self.assertIn(Path(result['cv_pdf']).parent.name, publication['cv_url'])
        self.assertIn(Path(result['letter_pdf']).parent.name, publication['letter_url'])
        self.assertEqual(self.model_calls, ['Letter plan', 'Grounded letter', 'Letter verification'])

    def test_rejected_letter_attempts_are_reported_as_warnings(self):
        self.letters = [_letter(self.store, ' I also ran Kubernetes clusters and cut costs by 37 percent.'), _letter(self.store)]
        result, code = self.cli()
        self.assertEqual(code, 0)
        self.assertEqual(len(result['warnings']), 1)
        self.assertIn('letter attempt 1 rejected', result['warnings'][0])
        self.assertIn('Kubernetes', result['warnings'][0])

    # --- idempotence -----------------------------------------------------------------------------

    def test_second_run_returns_the_same_bundle_without_a_model_call(self):
        first, _ = self.cli()
        calls = len(self.model_calls)
        again, code = self.cli()
        self.assertEqual(code, 0)
        self.assertTrue(again['cached'])
        self.assertEqual(len(self.model_calls), calls)
        self.assertEqual((again['cv_pdf'], again['letter_pdf']), (first['cv_pdf'], first['letter_pdf']))
        self.assertEqual(again['validation'], first['validation'])
        self.assertEqual(len(self.revisions()), 2)

    def test_cached_result_keeps_the_original_warnings(self):
        self.letters = [_letter(self.store, ' I also ran Kubernetes clusters.'), _letter(self.store)]
        first, _ = self.cli()
        again, _ = self.cli()
        self.assertTrue(again['cached'])
        self.assertEqual(again['warnings'], first['warnings'])

    def test_force_rebuilds(self):
        first, _ = self.cli()
        forced, code = self.cli('--force')
        self.assertEqual(code, 0)
        self.assertFalse(forced['cached'])
        self.assertEqual(forced['regenerated_because'], '--force')
        self.assertNotEqual(forced['cv_pdf'], first['cv_pdf'])
        self.assertEqual(len(self.model_calls), 6)
        publication = json.loads((self.output / 'publication.json').read_text())
        self.assertIn(Path(forced['cv_pdf']).parent.name, publication['cv_url'])

    def test_changed_inputs_regenerate(self):
        self.cli()
        cases = {
            'job text': lambda: db.upsert_job(dict(self.job, description='A different posting text.'), user_id=self.user['id']),
            'CV': lambda: (Path(user_assets.user_profile_dir(self.name)) / 'CV-plaintext.txt').write_text(CV + '\n- Wrote tests.'),
        }
        for label, change in cases.items():
            with self.subTest(label):
                change()
                result, code = self.cli()
                self.assertEqual(code, 0)
                self.assertFalse(result['cached'], label)
                self.assertIn('inputs changed', result['regenerated_because'])
                self.assertTrue(self.cli()[0]['cached'])  # and the new bundle is now the current one

    def test_model_change_regenerates(self):
        self.cli()
        (Path(user_assets.user_profile_dir(self.name)) / 'scraper_config.json').write_text(json.dumps(
            {'document_model': 'other-model', 'auto_generate': {'document_engine': 'latex'}}))
        result, _ = self.cli()
        self.assertFalse(result['cached'])
        self.assertEqual(result['model'], 'other-model')

    def test_bundle_is_reused_only_on_the_day_it_was_made(self):
        self.cli()
        with patch.object(generate_for_job, '_today', return_value='2999-01-01'):
            result, _ = self.cli()
        self.assertFalse(result['cached'])
        self.assertIn('dated', result['regenerated_because'])

    def test_republished_or_damaged_bundle_is_not_reused(self):
        first, _ = self.cli()
        pdf = Path(first['letter_pdf'])
        pdf.write_bytes(pdf.read_bytes() + b'\n% tampered')
        result, code = self.cli()
        self.assertEqual(code, 0)
        self.assertFalse(result['cached'])
        self.assertIn('no longer matches', result['regenerated_because'])
        publication = json.loads((self.output / 'publication.json').read_text())
        publication['cv_url'] = publication['cv_url'].replace('/revisions/', '/revisions/other', 1)
        (self.output / 'publication.json').write_text(json.dumps(publication))
        result, _ = self.cli()
        self.assertFalse(result['cached'])
        self.assertIn('republished', result['regenerated_because'])

    def test_concurrent_runs_generate_once(self):
        results = []

        def work():
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                result, code = generate_for_job.run(self.name, self.job_id)
            results.append((result, code))

        slow = self._model

        def slow_model(prompt, **kwargs):
            time.sleep(0.3)
            return slow(prompt, **kwargs)

        with patch('jobweaver.generators.run_ai_prompt', side_effect=slow_model):
            threads = [threading.Thread(target=work) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
        self.assertEqual([code for _, code in results], [0, 0])
        self.assertEqual(sorted(r['cached'] for r, _ in results), [False, True])
        self.assertEqual(len(self.model_calls), 3)
        self.assertEqual(len(self.revisions()), 2)

    # --- failure ---------------------------------------------------------------------------------

    def test_terminal_letter_failure_removes_atomic_cv_bundle(self):
        from jobweaver.operation_budget import OperationExhausted
        with patch('jobweaver.generators.run_ai_prompt', side_effect=OperationExhausted('Operation allowance exhausted')):
            result, code = self.cli()
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertEqual(self.revisions(), [])
        self.assertFalse((self.output / 'publication.json').exists())
        self.assertFalse((self.output / generate_for_job.GENERATION_FILE).exists())

    def test_failed_first_run_publishes_nothing(self):
        self.letters = ['not json at all']
        result, code = self.cli()
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertIsNone(result['cv_pdf'])
        self.assertTrue(any(error.startswith('letter:') for error in result['errors']), result['errors'])
        self.assertEqual(len(result['warnings']), 3)
        self.assertFalse((self.output / 'publication.json').exists())
        self.assertFalse((self.output / generate_for_job.GENERATION_FILE).exists())
        self.assertEqual(self.revisions(), [], 'the CV that was built before the letter failed must be removed')

    def test_failed_rebuild_keeps_the_last_good_documents_active(self):
        good, _ = self.cli()
        snapshot = {
            'publication': (self.output / 'publication.json').read_bytes(),
            'generation': (self.output / generate_for_job.GENERATION_FILE).read_bytes(),
            'revisions': self.revisions(), 'cv': Path(good['cv_pdf']).read_bytes(), 'letter': Path(good['letter_pdf']).read_bytes(),
        }
        self.letters = ['not json at all']
        result, code = self.cli('--force')
        self.assertEqual(code, 1)
        self.assertFalse(result['ok'])
        self.assertEqual((self.output / 'publication.json').read_bytes(), snapshot['publication'])
        self.assertEqual((self.output / generate_for_job.GENERATION_FILE).read_bytes(), snapshot['generation'])
        self.assertEqual(self.revisions(), snapshot['revisions'])
        self.assertEqual(Path(good['cv_pdf']).read_bytes(), snapshot['cv'])
        self.assertEqual(Path(good['letter_pdf']).read_bytes(), snapshot['letter'])
        again, code = self.cli()
        self.assertEqual(code, 0)
        self.assertTrue(again['cached'])
        self.assertEqual(again['cv_pdf'], good['cv_pdf'])

    def test_unknown_job_user_and_usage_give_json_and_exit_2(self):
        result, code = self.cli(job='li_does_not_exist')
        self.assertEqual((code, result['ok']), (2, False))
        self.assertIn('job not found', result['errors'][0])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = generate_for_job.main(['--user', 'nobody-here', '--job', self.job_id])
        self.assertEqual(code, 2)
        self.assertIn('unknown user', json.loads(buffer.getvalue())['errors'][0])
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer), self.assertRaises(SystemExit) as raised:
            generate_for_job.main(['--user', self.name])
        self.assertEqual(raised.exception.code, 2)
        self.assertFalse(json.loads(buffer.getvalue())['ok'])

    def test_missing_cv_is_reported(self):
        (Path(user_assets.user_profile_dir(self.name)) / 'CV-plaintext.txt').unlink()
        result, code = self.cli()
        self.assertEqual(code, 2)
        self.assertIn('CV-plaintext.txt', result['errors'][0])
        self.assertEqual(self.model_calls, [])

    # --- the shared document pipeline ---------------------------------------------------------

    def _generate(self, **kwargs):
        user = {'id': self.user['id'], 'username': self.name}
        return daily_scraper._generate_docs_for_job(self.job, model_name='mock', tone='professional', cv_text=CV,
                                                    user=user, compact=False, **kwargs)

    def test_incremental_mode_still_publishes_each_document_as_it_is_built(self):
        self.letters = ['not json at all']
        outcome = self._generate()
        self.assertFalse(outcome['success'])
        self.assertEqual(len(outcome['files']), 1)
        publication = json.loads((self.output / 'publication.json').read_text())
        self.assertIn('cv_url', publication)
        self.assertNotIn('letter_url', publication)
        self.assertEqual(len(self.revisions()), 1)

    def test_incremental_mode_success_returns_both_files(self):
        outcome = self._generate()
        self.assertTrue(outcome['success'])
        self.assertEqual([Path(p).name for p in outcome['files']], ['CV-SyntheticCo.pdf', 'Letter-SyntheticCo.pdf'])
        publication = json.loads((self.output / 'publication.json').read_text())
        self.assertEqual(publication['revision'], outcome['built']['letter']['revision'])

    def test_download_names(self):
        name = reviewed_documents.download_name
        self.assertEqual(name(self.name, 'CV-Acme.pdf', CV), 'Synthetic_Applicant_CV.pdf')
        self.assertEqual(name(self.name, 'Letter-Acme.pdf', CV), 'Synthetic_Applicant_Cover_Letter.pdf')
        self.assertEqual(name(self.name, 'other.pdf', CV), 'other.pdf')
        self.assertEqual(name(self.name, 'CV-Acme.pdf', None), f'{self.name}_CV.pdf')


if __name__ == '__main__':
    unittest.main()
