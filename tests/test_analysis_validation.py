import hashlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import analysis_validation
import scrapers


class AnalysisValidationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name) / 'diagnostics'
        env = patch.dict(os.environ, JOBWEAVER_ANALYSIS_DIAGNOSTICS_DIR=str(self.directory))
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def response(**changes):
        return json.dumps({'german_level': 'none', 'summary': 'Posting', 'match_score': 80, **changes})

    def records(self):
        return [json.loads(path.read_text()) for path in sorted(self.directory.glob('failure-*.json'))]

    def test_real_source_whitespace_quotes_store_original_spans(self):
        examples = [
            ('Sehr gute\u00a0Deutschkenntnisse\u00a0(ab C1)', 'Sehr gute Deutschkenntnisse (ab C1)'),
            ('Deutsch- und\n\nEnglischkenntnisse in Wort und Schrift',
             'Deutsch- und Englischkenntnisse in Wort und Schrift'),
        ]
        for original, quote in examples:
            with self.subTest(original=original), patch('scrapers.run_ai_prompt', return_value=json.dumps({
                'german_level': 'C1', 'summary': 'Posting', 'german_strength': 'required',
                'german_evidence': quote,
                'constraints': [{'kind': 'german', 'strength': 'required', 'value': 'C1', 'evidence': quote}],
            })) as model:
                result = scrapers.process_job_with_ai('Intro ' + original + ' end', denoise=False)
                self.assertEqual(result['german_evidence'], original)
                self.assertEqual(result['constraints'][0]['evidence'], original)
                self.assertEqual(model.call_count, 1)

    def test_exact_match_preferred_and_other_whitespace_preserved(self):
        source = 'German\nrequired, German required; English\t  preferred.'
        with patch('scrapers.run_ai_prompt', return_value=self.response(
            german_evidence='German required', constraints=[{'kind': 'other', 'strength': 'preferred',
            'value': 'English', 'evidence': 'English preferred.'}])):
            result = scrapers.process_job_with_ai(source, denoise=False)
        self.assertEqual(result['german_evidence'], 'German required')
        self.assertEqual(result['constraints'][0]['evidence'], 'English\t  preferred.')

    def test_schema_retry_with_specific_feedback(self):
        bad = self.response(constraints=[{'kind': 'german', 'strength': 'none', 'value': 'none', 'evidence': ''}])
        with patch('scrapers.run_ai_prompt', side_effect=[bad, self.response()]) as model:
            result = scrapers.process_job_with_ai('Posting', 'Synthetic CV', denoise=False)
        self.assertEqual(result['analysis_state'], 'complete')
        self.assertEqual(model.call_count, 2)
        self.assertIn('constraints.0.strength', model.call_args_list[1].args[0])
        self.assertIn("'required', 'preferred' or 'unknown'", model.call_args_list[1].args[0])
        self.assertEqual(self.records()[0]['attempt'], 1)
        self.assertEqual(self.records()[0]['extraction']['constraints'][0]['strength'], 'none')

    def test_evidence_retry_records_initial_failure_before_second_call(self):
        bad = self.response(german_evidence='Invented quote')
        def second(prompt, **kwargs):
            records = self.records()
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['response']['sha256'], hashlib.sha256(bad.encode()).hexdigest())
            self.assertEqual(records[0]['issues'][0]['path'], 'german_evidence')
            self.assertIn('german_evidence', prompt)
            self.assertIn('absent from the original posting', prompt)
            return self.response(german_evidence='German required')
        with patch('scrapers.run_ai_prompt') as model:
            model.side_effect = lambda *a, **kw: bad if model.call_count == 1 else second(*a, **kw)
            result = scrapers.process_job_with_ai('German required', denoise=False)
        self.assertEqual(result['german_evidence'], 'German required')
        self.assertEqual(model.call_count, 2)

    def test_ungrounded_variants_exhaust_and_fail_closed(self):
        for quote in ('Fluent German mandatory', 'german required.', 'German required!',
                      'Deutsch erforderlich.', 'German English', 'German is required.'):
            with self.subTest(quote=quote), patch('scrapers.run_ai_prompt', return_value=self.response(
                german_evidence=quote)) as model, self.assertRaises(ValueError):
                scrapers.process_job_with_ai('German required. Extra words English', denoise=False)
            self.assertEqual(model.call_count, 2)

    def test_missing_required_quotes_and_invalid_scores_still_fail(self):
        for changes in ({'german_strength': 'required', 'german_evidence': ''},
                        {'constraints': [{'kind': 'other', 'strength': 'preferred', 'value': 'x', 'evidence': ' '}]},
                        *({'match_score': score} for score in (None, True, '80', -1, 101))):
            with self.subTest(changes=changes), patch('scrapers.run_ai_prompt', return_value=self.response(
                **changes)) as model, self.assertRaises(ValueError):
                scrapers.process_job_with_ai('Posting', 'Synthetic CV', denoise=False)
            self.assertEqual(model.call_count, 2)

    def test_cleanup_json_fallback_and_validation_share_budget(self):
        with patch('scrapers.run_ai_prompt', side_effect=['broken JSON', self.response(german_evidence='invented'),
                                                           self.response()]) as model, self.assertRaises(ValueError):
            scrapers.process_job_with_ai('Posting', denoise=True)
        self.assertEqual(model.call_count, 2)
        self.assertIn('cleaned_description', model.call_args_list[0].args[0])
        self.assertNotIn('cleaned_description', model.call_args_list[1].args[0])
        self.assertEqual([record['attempt'] for record in self.records()], [1, 2])

    def test_cleanup_json_fallback_succeeds(self):
        with patch('scrapers.run_ai_prompt', side_effect=['broken JSON', self.response()]) as model:
            result = scrapers.process_job_with_ai('Posting', denoise=True)
        self.assertEqual(result['analysis_state'], 'complete')
        self.assertEqual(model.call_count, 2)

    def test_invalid_json_without_cleanup_gets_one_retry(self):
        with patch('scrapers.run_ai_prompt', return_value='broken JSON') as model, self.assertRaises(ValueError):
            scrapers.process_job_with_ai('Posting', denoise=False)
        self.assertEqual(model.call_count, 2)
        self.assertIn('invalid JSON', model.call_args_list[1].args[0])
        with patch('scrapers.run_ai_prompt', side_effect=['broken JSON', self.response()]):
            self.assertEqual(scrapers.process_job_with_ai('Posting', denoise=False)['analysis_state'], 'complete')

    def test_truncated_response_retried_once_shorter_without_echo(self):
        from generators import AITruncatedError
        with patch('scrapers.run_ai_prompt', side_effect=[AITruncatedError('cut'), self.response()]) as model:
            result = scrapers.process_job_with_ai('Posting', denoise=True)
        self.assertEqual(result['analysis_state'], 'complete')
        self.assertIn('cleaned_description', model.call_args_list[0].args[0])
        self.assertNotIn('cleaned_description', model.call_args_list[1].args[0])
        self.assertIn('cut off at the length limit', model.call_args_list[1].args[0])
        with patch('scrapers.run_ai_prompt', side_effect=AITruncatedError('cut')) as model, \
                self.assertRaises(AITruncatedError):
            scrapers.process_job_with_ai('Posting', denoise=False)
        self.assertEqual(model.call_count, 2)

    def test_extra_keys_in_analysis_points_are_dropped(self):
        point = {'title': 'Python', 'detail': 'Uses Python daily.', 'evidence': 'extra key'}
        with patch('scrapers.run_ai_prompt', return_value=self.response(
                match_analysis={'strengths': [point], 'gaps': [point], 'tips': [point]})) as model:
            result = scrapers.process_job_with_ai('Posting', 'Synthetic CV', denoise=False)
        self.assertEqual(model.call_count, 1)
        self.assertEqual(result['match_analysis']['strengths'], [{'title': 'Python', 'detail': 'Uses Python daily.'}])

    def test_provider_errors_are_not_retried(self):
        from requests import HTTPError, Response
        for status in (400, 401, 403, 404, 422, 429, 500):
            response = Response()
            response.status_code = status
            error = HTTPError('Private provider details', response=response)
            for denoise in (False, True):
                with self.subTest(status=status, denoise=denoise), patch('scrapers.run_ai_prompt', side_effect=error) as model:
                    with self.assertRaises(HTTPError):
                        scrapers.process_job_with_ai('Posting', denoise=denoise)
                self.assertEqual(model.call_count, 1)
        for error in (TimeoutError('private'), ConnectionError('private'), RuntimeError('private')):
            with patch('scrapers.run_ai_prompt', side_effect=error) as model, self.assertRaises(type(error)):
                scrapers.process_job_with_ai('Posting', denoise=True)
            self.assertEqual(model.call_count, 1)
        self.assertEqual(self.records(), [])

    def test_diagnostics_do_not_save_cv_or_model_prose(self):
        secret = 'CV-PRIVATE-SECRET candidate background and auth token'
        bad = self.response(summary=secret, german_evidence=secret,
            constraints=[{'kind': 'other', 'strength': 'required', 'value': secret, 'evidence': secret}],
            match_analysis={'synthesis': secret, 'strengths': [{'title': secret, 'detail': secret}]})
        with patch('scrapers.run_ai_prompt', return_value=bad) as model, self.assertRaises(ValueError) as raised:
            scrapers.process_job_with_ai('Posting', secret, model_name='offline-test', denoise=False)
        self.assertNotIn(secret, str(raised.exception))
        records = self.records()
        self.assertEqual(len(records), 2)
        for path in self.directory.glob('failure-*.json'):
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn(secret, path.read_text())
            self.assertNotIn('match_analysis', path.read_text())
        self.assertEqual(self.directory.stat().st_mode & 0o777, 0o700)
        self.assertEqual(records[0]['model'], 'offline-test')
        self.assertEqual(records[0]['source_sha256'], hashlib.sha256(b'Posting').hexdigest())
        self.assertIn('timestamp', records[0])
        self.assertEqual(model.call_count, 2)

    def test_schema_diagnostics_exclude_input_and_unknown_field_names(self):
        secret = 'PRIVATE-CV-TEXT'
        bad = self.response(match_analysis={'strengths': [secret]}, constraints=[{
            'kind': 'other', 'strength': 'required', 'value': secret, 'evidence': '', secret: secret}])
        with patch('scrapers.run_ai_prompt', return_value=bad), self.assertRaises(ValueError) as raised:
            scrapers.process_job_with_ai('Posting', secret, denoise=False)
        self.assertNotIn(secret, str(raised.exception))
        for record in self.records():
            self.assertNotIn(secret, json.dumps(record))
            for issue in record['issues']:
                self.assertNotIn('input', issue)
                self.assertNotIn('ctx', issue)

    def test_raw_description_grounding_survives_denoise(self):
        source = 'German required.'
        with patch('scrapers.clean_job_description_noise', return_value='Invented by cleaner'), patch(
            'scrapers.run_ai_prompt', return_value=self.response(german_evidence='Invented by cleaner')) as model:
            with self.assertRaises(ValueError):
                scrapers.process_job_with_ai(source, denoise=True)
        self.assertEqual(model.call_count, 2)

    def test_failure_writer_error_does_not_block_correction(self):
        self.directory.parent.joinpath('diagnostics').write_text('not a directory')
        with patch('scrapers.run_ai_prompt', side_effect=[self.response(german_evidence='invented'), self.response()]):
            self.assertEqual(scrapers.process_job_with_ai('Posting', denoise=False)['analysis_state'], 'complete')

    def test_real_prompt_helper_does_not_stack_provider_retries(self):
        import generators
        for outputs in ([self.response(german_evidence='invented'), self.response()],
                        [generators.AIContentFilterError('filter'), self.response(german_evidence='invented')],
                        [TimeoutError('offline timeout')]):
            with self.subTest(outputs=len(outputs)), patch('scrapers.run_ai_prompt', wraps=generators.run_ai_prompt), patch(
                    'generators.openrouter_api', side_effect=outputs) as provider:
                if len(outputs) == 2 and isinstance(outputs[0], str):
                    result = scrapers.process_job_with_ai('Posting', denoise=True)
                    self.assertEqual(result['analysis_state'], 'complete')
                else:
                    with self.assertRaises((ValueError, TimeoutError)):
                        scrapers.process_job_with_ai('Posting', denoise=True)
                self.assertEqual(provider.call_count, len(outputs))

    def test_diagnostic_size_bounded_even_if_model_echoes_large_cv(self):
        secret = 'PRIVATE CANDIDATE PROSE ' * 1000
        constraints = [{'kind': 'other', 'strength': 'required', 'value': secret, 'evidence': secret}] * 100
        with patch('scrapers.run_ai_prompt', return_value=self.response(constraints=constraints)), self.assertRaises(ValueError):
            scrapers.process_job_with_ai('Posting', secret, denoise=False)
        for path in self.directory.glob('failure-*.json'):
            self.assertLess(path.stat().st_size, 50000)
            record = json.loads(path.read_text())
            self.assertEqual(record['extraction']['constraints_count'], 100)
            self.assertEqual(len(record['extraction']['constraints']), 64)
            self.assertEqual(len(record['issues']), 64)

    def test_unique_concurrent_diagnostics_and_retention(self):
        def reject(_):
            with self.assertRaises(ValueError):
                scrapers.process_job_with_ai('Posting', denoise=False)
        with patch('scrapers.run_ai_prompt', return_value=self.response(german_evidence='invented')):
            with ThreadPoolExecutor(max_workers=5) as pool:
                list(pool.map(reject, range(10)))
        self.assertEqual(len(self.records()), 20)
        for record in self.records():
            self.assertIn(record['attempt'], (1, 2))
        oldest = sorted(self.directory.glob('failure-*.json'))[0]
        os.utime(oldest, (1, 1))
        with patch.object(analysis_validation, 'MAX_RECORDS', 3), patch('scrapers.run_ai_prompt',
                side_effect=[self.response(german_evidence='invented'), self.response()]):
            scrapers.process_job_with_ai('Posting', denoise=False)
        self.assertEqual(len(self.records()), 3)
        self.assertFalse(oldest.exists())
