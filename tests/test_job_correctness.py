import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch
from jobweaver import db
from jobweaver import scrapers
from jobweaver import server
from jobweaver.job_policy import eligibility, qualifies


class ExtractionValidationTest(unittest.TestCase):
    def analyze(self, **changes):
        response = {'german_level': 'none', 'summary': 'Synthetic job', 'match_checks': [{'requirement': 'Synthetic skill', 'importance': 'must', 'posting_quote': 'Synthetic job', 'coverage': 'shown', 'cv_quote': 'Synthetic CV'}], **changes}
        with patch('jobweaver.scrapers.run_ai_prompt', return_value=json.dumps(response)):
            return scrapers.process_job_with_ai('Synthetic job with German preferred', 'Synthetic CV', denoise=False)

    def test_bad_checks_and_shapes_rejected(self):
        for value in (None, True, 'checks', [42], [{'requirement': 'X'}]):
            with self.subTest(checks=value), self.assertRaises(ValueError):
                self.analyze(match_checks=value)
        with self.assertRaises(ValueError):
            self.analyze(match_analysis={'strengths': [42], 'gaps': 'oops'})
        with patch('jobweaver.scrapers.run_ai_prompt', return_value='{}'), self.assertRaises(ValueError):
            scrapers.process_job_with_ai('posting', 'CV', denoise=False)

    def test_tier_is_derived_and_raw_posting_retained(self):
        result = self.analyze(match_score=95, match_analysis={'tier': 'Reach'}, cleaned_description='Invented content ' * 50)
        self.assertEqual(result['match_rating'], 'Great')
        self.assertIsNone(result['match_score'])
        self.assertEqual(result['raw_description'], 'Synthetic job with German preferred')
        self.assertEqual(result['description'], result['raw_description'])

    def test_quote_must_exist(self):
        with self.assertRaises(ValueError):
            self.analyze(german_evidence='Fluent German mandatory')

    def test_non_austrian_monthly_and_usd_are_not_eur_x14(self):
        self.assertIsNone(self.analyze(salary_amount=4000, salary_period='month', salary_currency='EUR', salary_country='DE')['salary_yearly'])
        self.assertEqual(self.analyze(salary_amount=4000, salary_period='month', salary_currency='EUR', salary_country='DE', salary_payments=12)['salary_yearly'], 48000)
        self.assertIsNone(self.analyze(salary_amount=60000, salary_period='year', salary_currency='USD')['salary_yearly'])

    def test_eligibility_is_distinct_from_score(self):
        cfg = {'auto_generate': {'max_german_level': 'B1', 'min_match_score': 65}}
        job = {'german_level': 'C1', 'german_strength': 'required', 'match_score': 99}
        self.assertEqual(eligibility(job, cfg)['state'], 'ineligible')
        self.assertFalse(qualifies(job, cfg))
        job['german_strength'] = 'preferred'
        self.assertEqual(eligibility(job, cfg)['state'], 'eligible')
        job['german_strength'] = 'unknown'
        self.assertEqual(eligibility(job, cfg)['state'], 'needs_review')
        job.update(german_level='none', constraints=[{'kind': 'work_authorization', 'value': 'DE', 'strength': 'required'}])
        self.assertEqual(eligibility(job, cfg)['state'], 'needs_review')


def feed(rows, errors=()):
    """Serve `rows` as one company-feed run (the stand-in Source for pipeline tests)."""
    rows = [{'source': 'Company feed (Greenhouse)', **row} for row in rows]
    return patch.multiple('jobweaver.company_feeds', load_companies=MagicMock(return_value={'companies': []}),
                          fetch_company_postings=MagicMock(return_value=(rows, list(errors))))


class PostingLifecycleTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        previous = db.DB_PATH
        self.addCleanup(db.set_db_path, previous)
        db.set_db_path(os.path.join(self.temp.name, 'synthetic.db'))
        db.init_db()
        self.user = {'id': 1, 'username': 'synthetic'}

    def test_url_conflict_preserves_identity_and_application_state(self):
        db.upsert_job({'id': 'old', 'job_url': 'https://example.invalid/1', 'status': 'applied',
                       'application_date': '2026-09-20', 'raw_description': 'Version one'}, user_id=1)
        db.upsert_job({'id': 'different', 'job_url': 'https://example.invalid/1', 'status': 'new',
                       'raw_description': 'Version two'}, user_id=1)
        record = db.get_job_by_id('old', 1)
        self.assertEqual(record['status'], 'applied')
        self.assertEqual(record['application_date'], '2026-09-20')
        self.assertEqual(record['posting_history'][0]['raw_description'], 'Version one')
        self.assertIsNone(db.get_job_by_id('different', 1))

    def test_duplicates_use_one_analysis_and_revision_preserves_status(self):
        rows = [{'id': 'one', 'job_url': 'https://example.invalid/1', 'description': 'Version one', 'title': 'T', 'company': 'C'},
                {'id': 'two', 'job_url': 'https://example.invalid/1', 'description': 'Version one', 'title': 'T', 'company': 'C'}]
        def analysis(text, *args, **kwargs):
            return {'raw_description': text, 'description': text, 'german_level': 'none', 'requires_german': False,
                    'salary': 'Not Specified', 'skills': '', 'summary': 'Synthetic', 'match_score': 80}
        with feed(rows), patch('jobweaver.scrapers.process_job_with_ai', side_effect=analysis) as ai:
            result = scrapers.scrape_new_jobs(scrapers.ScrapeParams(source='company-feeds'), user=self.user, cv_text='CV')
            self.assertEqual(ai.call_count, 1)
            self.assertEqual(result['new_jobs_count'], 1)
        record = db.get_job_by_url('https://example.invalid/1', 1)
        db.update_job_fields(record['id'], user_id=1, status='applied')
        with feed([{**rows[0], 'description': 'Version two'}]), patch('jobweaver.scrapers.process_job_with_ai', side_effect=analysis):
            scrapers.scrape_new_jobs(scrapers.ScrapeParams(source='company-feeds'), user=self.user, cv_text='CV')
        self.assertEqual(db.get_job_by_url('https://example.invalid/1', 1)['status'], 'applied')

    def _analysis(self, text, *args, **kwargs):
        return {'raw_description': text, 'description': text, 'german_level': 'none', 'requires_german': False,
                'salary': 'Not Specified', 'skills': '', 'summary': 'Synthetic', 'match_score': 80}

    def test_gate_rejects_and_logs_records_without_required_fields(self):
        good = {'id': 'ds_1', 'job_url': 'https://example.invalid/1', 'title': 'Good', 'company': 'C',
                'description': 'Text', 'emails': ['someone@example.invalid']}
        rows = [good, {**good, 'id': '', 'job_url': 'https://example.invalid/2', 'title': 'No id'},
                {**good, 'id': 'ds_3', 'job_url': 'https://example.invalid/3', 'title': 'No text', 'description': ''}]
        logs = []
        with feed(rows), patch('jobweaver.scrapers.process_job_with_ai', side_effect=self._analysis):
            result = scrapers.scrape_new_jobs(scrapers.ScrapeParams(source='company-feeds'), user=self.user, cv_text='CV',
                                              log_fn=lambda msg, level='info': logs.append((level, msg)))
        self.assertEqual(result['new_jobs_count'], 1)
        self.assertNotIn('emails', db.get_job_by_id('ds_1', 1))
        self.assertIsNone(db.get_job_by_url('https://example.invalid/2', 1))
        self.assertIsNone(db.get_job_by_id('ds_3', 1))
        rejected = [msg for level, msg in logs if 'rejected 2 of 3' in msg]
        self.assertEqual(len(rejected), 1)
        self.assertIn("'No id'", rejected[0])
        # Two of three rejected is far above the usual share: the run reports that the Source may have changed.
        self.assertFalse(result['success'])

    def test_every_record_rejected_is_a_failed_run(self):
        rows = [{'id': 'x', 'job_url': 'https://example.invalid/1', 'title': 'T', 'company': 'C', 'description': ''}]
        with feed(rows), patch('jobweaver.scrapers.process_job_with_ai') as ai:
            result = scrapers.scrape_new_jobs(scrapers.ScrapeParams(source='company-feeds'), user=self.user)
        self.assertEqual(result['state'], 'failed')
        ai.assert_not_called()

    def test_a_field_missing_later_keeps_the_stored_value(self):
        first = {'id': 'ds_9', 'job_url': 'https://example.invalid/9', 'title': 'T', 'company': 'C',
                 'description': 'Version one', 'location': 'Wien'}
        later = [{**first, 'description': 'Version two', 'location': None},
                 {**first, 'id': 'ds_10', 'job_url': 'https://example.invalid/10', 'description': 'Other'}]
        with feed([first]), patch('jobweaver.scrapers.process_job_with_ai', side_effect=self._analysis):
            scrapers.scrape_new_jobs(scrapers.ScrapeParams(source='company-feeds'), user=self.user, cv_text='CV')
        with feed(later), patch('jobweaver.scrapers.process_job_with_ai', side_effect=self._analysis):
            scrapers.scrape_new_jobs(scrapers.ScrapeParams(source='company-feeds'), user=self.user, cv_text='CV')
        self.assertEqual(db.get_job_by_id('ds_9', 1)['location'], 'Wien')

    def test_manual_failure_is_saved_and_retryable(self):
        with patch('jobweaver.server._scrapers.process_job_with_ai', side_effect=ValueError('bad response')):
            result = server.add_job_manual(server.ManualJobRequest(title='Synthetic', description='Posting'), user=self.user)
        self.assertFalse(result['success'])
        self.assertTrue(result['saved'])
        self.assertEqual(db.get_job_by_id(result['job_id'], 1)['processed'], 0)

    def test_source_failure_is_not_successful_empty(self):
        with feed([], ['Search failed']):
            result = scrapers.scrape_new_jobs(scrapers.ScrapeParams(source='company-feeds'), user=self.user)
        self.assertFalse(result['success'])
        self.assertEqual(result['state'], 'failed')

    def test_daily_policy_current_scores_and_revision_urls(self):
        from jobweaver.job_policy import fingerprint
        from pathlib import Path
        output = Path(self.temp.name, 'Synthetic_daily')
        output.mkdir()
        (output / 'publication.json').write_text(json.dumps({'cv_url': '/api/download/Synthetic_daily/revisions/one/CV-Synthetic.pdf'}))
        config = {'auto_generate': {'min_match_score': 70, 'max_german_level': 'B1'}}
        record = {'id': 'daily', 'company': 'Synthetic', 'date_scraped': '2026-10-01', 'processed': 1,
                  'analysis_schema': 2, 'analysis_state': 'complete', 'match_rating': 'Great', 'match_checks': [{'requirement': 'Python', 'importance': 'must', 'posting_quote': 'Python required', 'coverage': 'shown', 'cv_quote': 'CV'}], 'german_level': 'none', 'german_strength': 'none',
                  'analysis_fingerprint': fingerprint('CV', 'mock')}
        db.upsert_job(record, user_id=1)
        # Pending null scores cause pandas to represent the validated score as 80.0.
        db.upsert_job({**record, 'id': 'pending', 'match_score': None, 'match_rating': None, 'match_checks': [], 'analysis_schema': None, 'analysis_fingerprint': None, 'processed': 0}, user_id=1)
        with patch('jobweaver.server.load_user_config_dict', return_value=config), patch('jobweaver.server.load_cv_text', return_value='CV'), patch('jobweaver.server._effective_ai_model', return_value='mock'), patch('jobweaver.server.user_outputs_dir', return_value=self.temp.name):
            response = server.get_daily_results('2026-10-01', user=self.user)
            self.assertEqual([job['id'] for job in response['jobs']], ['daily'])
            self.assertIn('/revisions/', response['jobs'][0]['cv_url'])
        with patch('jobweaver.server.load_user_config_dict', return_value=config), patch('jobweaver.server.load_cv_text', return_value='CHANGED CV'), patch('jobweaver.server._effective_ai_model', return_value='mock'), patch('jobweaver.server.user_outputs_dir', return_value=self.temp.name):
            self.assertEqual(server.get_daily_results('2026-10-01', user=self.user)['jobs'], [])

    def test_conflicting_id_and_url_never_merge_two_applications(self):
        db.upsert_job({'id': 'first', 'job_url': 'https://example.invalid/a', 'status': 'applied'}, user_id=1)
        db.upsert_job({'id': 'second', 'job_url': 'https://example.invalid/b', 'status': 'interview'}, user_id=1)
        with self.assertRaisesRegex(ValueError, 'identity conflicts'):
            db.upsert_job({'id': 'first', 'job_url': 'https://example.invalid/b', 'status': 'new'}, user_id=1)
        self.assertEqual(db.get_job_by_id('first', 1)['status'], 'applied')
        self.assertEqual(db.get_job_by_id('second', 1)['status'], 'interview')
