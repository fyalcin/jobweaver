"""Bounded HTTP/cron inputs, tested only through the isolated runner."""
import asyncio
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

import company_feeds as feeds
import auth
import daily_scraper
import db
import input_limits as limits
import request_limits
import scrapers
import server
import user_assets
from pdf_fixture import pdf_bytes


class InputContractsTest(unittest.TestCase):
    def test_sources_and_numeric_boundaries_match_request_and_python(self):
        for source, maximum in [('linkedin-apify', 500), ('karriere-apify', 200), ('company-feeds', 500)]:
            for cls in (server.ScrapeRequest, scrapers.ScrapeParams):
                valid = dict(keywords='Physik, Python', source=source,
                             results_limit=maximum, hours_old=720, distance=200)
                self.assertEqual(cls(**valid).results_limit, maximum)
                for override in ({'results_limit': maximum + 1}, {'results_limit': 0},
                                 {'hours_old': 721}, {'distance': 201}, {'source': 'karriere'},
                                 {'results_limit': True}, {'hours_old': 1.5}):
                    with self.subTest(cls=cls, override=override), self.assertRaises(ValueError):
                        cls(**{**valid, **override})

    def test_keyword_phrase_and_combined_limits(self):
        self.assertEqual(len(limits.keyword_list(['ü' * 199] * 20)), 20)
        for value in (['x'] * 21, 'x' * 501, ['x' * 200] * 20, [{'q': 'python'}], 42):
            with self.subTest(value=str(value)[:40]), self.assertRaises(ValueError):
                limits.keyword_list(value)
        self.assertEqual(limits.keyword_list(' Python, Physik '), ['Python', 'Physik'])

    def test_model_text_batch_and_element_boundaries(self):
        server.GenerateRequest(job_id='ü' * 512, modelName='ü' * 200, tone='ü' * 20_000)
        server.BatchGenerateRequest(job_ids=['job'] * 300)
        for payload in ({'job_id': 'x' * 513}, {'job_id': 'j', 'modelName': 'x' * 201},
                        {'job_id': 'j', 'tone': 'x' * 20_001}):
            with self.assertRaises(ValidationError):
                server.GenerateRequest(**payload)
        for ids in ([], ['j'] * 301, ['x' * 513]):
            with self.assertRaises(ValidationError):
                server.BatchGenerateRequest(job_ids=ids)
        with self.assertRaises(ValidationError):
            server.JobDocAiEditRequest(tex='x' * 1_000_001, instruction='edit')
        with self.assertRaises(ValidationError):
            server.AiEditDocumentRequest(instruction='x' * 20_001)

    def test_cron_validates_all_settings_before_any_scrape(self):
        invalid = [
            {'daily_scraper': {'linkedin': {'results_limit': 501}}},
            {'daily_scraper': {'karriere': {'keywords': ['x'] * 21}}},
            {'daily_scraper': {'lanes': [{'name': 'bridge', 'keywords': ['x'] * 20,
                                         'results_limit': 201}]}},
            {'daily_scraper': {'lanes': [{'name': 'x'}] * 21}},
            {'openrouter_model': 'x' * 201},
            {'auto_generate': {'tone': 'x' * 20_001}},
        ]
        for config in invalid:
            with self.subTest(config=str(config)[:60]), \
                    patch.object(daily_scraper, 'load_config', return_value=config), \
                    patch.object(daily_scraper, 'scrape_new_jobs') as scrape, \
                    self.assertRaises(ValidationError):
                daily_scraper._run_daily_for_user({'id': 1, 'username': 'fictional'})
            scrape.assert_not_called()
        with patch.object(daily_scraper.db, 'list_users') as users, self.assertRaises(ValueError):
            daily_scraper.run_daily_scraping(linkedin_limit=501)
        users.assert_not_called()

    def test_cli_rejects_invalid_override_without_starting_daily_work(self):
        result = subprocess.run([sys.executable, 'daily_scraper.py', '--linkedin-limit', '501'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn('less than or equal to 500', result.stderr)
        self.assertNotIn('Starting daily', result.stderr)

    def test_mutating_params_cannot_bypass_execution_validation(self):
        params = scrapers.ScrapeParams()
        params.results_limit = 501
        with patch.object(scrapers, '_load_scraper_settings') as load, self.assertRaises(ValueError):
            scrapers.scrape_new_jobs(params, user={'id': 1})
        load.assert_not_called()

    def test_nullable_cron_defaults_and_config_extensions_are_preserved(self):
        config = {'extension': {'keep': True}, 'daily_scraper': {
            'enable_karriere': True, 'extension': 'keep',
            'karriere': {'keywords': ['Python'], 'hours_old': None, 'distance': None}}}
        normalized = limits.validate_collection_config(config)
        self.assertEqual(normalized['extension'], config['extension'])
        self.assertEqual(normalized['daily_scraper']['extension'], 'keep')
        with patch.object(daily_scraper, 'load_config', return_value=config), \
                patch.object(daily_scraper, 'load_effective_cv', return_value=''), \
                patch.object(daily_scraper, 'scrape_new_jobs') as scrape, \
                patch.object(daily_scraper.db, 'load_jobs_by_date', return_value=__import__('pandas').DataFrame()):
            daily_scraper._run_daily_for_user({'id': 1, 'username': 'fictional'})
        params = scrape.call_args.args[0]
        self.assertEqual((params.hours_old, params.distance), (24, 10))

    def test_maximum_probe_tag_can_include_the_username(self):
        tag, username = 'ü' * 200, 'x' * 64
        limits.validate_daily_overrides(source_tag=tag)
        params = scrapers.ScrapeParams(label=f'{tag} [{username}]')
        self.assertEqual(len(params.label), 267)


class RawBodyTest(unittest.IsolatedAsyncioTestCase):
    async def request(self, path, chunks, headers=(), *, app=None, delay=0):
        scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1',
                 'scheme': 'http', 'method': 'POST', 'path': path, 'raw_path': path.encode(),
                 'query_string': b'', 'root_path': '', 'server': ('127.0.0.1', 80),
                 'client': ('127.0.0.1', 123),
                 'headers': [(b'host', b'127.0.0.1'), (b'content-type', b'application/json'), *headers]}
        messages, index = [], 0

        async def receive():
            nonlocal index
            if delay:
                await asyncio.sleep(delay)
            if index >= len(chunks):
                # Keep the client connected while the downstream application responds.
                await asyncio.Event().wait()
            part = chunks[index]
            index += 1
            return {'type': 'http.request', 'body': part, 'more_body': index < len(chunks)}

        await (app or server.app)(scope, receive, lambda msg: self._send(messages, msg))
        return next(m['status'] for m in messages if m['type'] == 'http.response.start'), messages, index

    async def _send(self, messages, msg):
        messages.append(msg)

    async def test_actual_bytes_rejected_before_json_auth_model_or_pdf_decode(self):
        # Small patched limits keep these hostile stream cases fast; production constants tested below.
        for path in ('/api/jobs/manual', '/api/jobs/one/documents/compile',
                     '/api/jobs/one/documents/finalize', '/api/documents/one/compile'):
            for headers in ([], [(b'content-length', b'1')], [(b'transfer-encoding', b'chunked')]):
                with self.subTest(path=path, headers=headers), \
                        patch.object(request_limits, 'GENERAL_BODY_BYTES', 64), \
                        patch.object(request_limits, 'PDF_BODY_BYTES', 64), \
                        patch.object(server, 'process_job_with_ai') as model, \
                        patch.object(server, 'decode_pdf') as decode:
                    dependency = Mock(side_effect=AssertionError('authentication ran before body admission'))
                    server.app.dependency_overrides[server.get_current_user] = dependency
                    self.addCleanup(server.app.dependency_overrides.clear)
                    status, messages, count = await self.request(path, [b'{', b'x' * 64], headers)
                    self.assertEqual(status, 413)
                    self.assertEqual(count, 2)
                    self.assertIn((b'connection', b'close'), messages[0]['headers'])
                    dependency.assert_not_called()
                    model.assert_not_called()
                    decode.assert_not_called()

    async def test_declared_excess_rejects_without_receiving(self):
        status, _, count = await self.request('/api/scrape', [],
                                              [(b'content-length', str(17 * 1024 * 1024).encode())])
        self.assertEqual((status, count), (413, 0))

    async def test_encodings_and_ambiguous_lengths_reject_before_receive(self):
        for headers, expected in [([(b'content-encoding', b'gzip')], 415),
                                  ([(b'content-encoding', b'identity, gzip')], 415),
                                  ([(b'content-length', b'-1')], 400),
                                  ([(b'content-length', b'1'), (b'content-length', b'1')], 400)]:
            status, _, count = await self.request('/api/scrape', [], headers)
            self.assertEqual((status, count), (expected, 0))

    async def test_slow_body_has_one_deadline_for_the_whole_stream(self):
        with patch.object(request_limits, 'RECEIVE_TIMEOUT_SECONDS', .03):
            status, _, _ = await self.request('/api/scrape', [b'{', b' ', b'}'], delay=.02)
        self.assertEqual(status, 408)

    async def test_production_caps_preserve_two_full_pdf_uploads(self):
        reached = Mock()

        async def downstream(scope, receive, send):
            body = (await receive())['body']
            value = server.JobDocFinalizeRequest.model_validate_json(body)
            reached(len(base64.b64decode(value.cv_pdf_base64)), len(base64.b64decode(value.letter_pdf_base64)))
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{}'})

        encoded = base64.b64encode(b'%PDF-' + b'x' * (12 * 1024 * 1024 - 5)).decode()
        payload = json.dumps({'cv_pdf_base64': encoded, 'letter_pdf_base64': encoded,
                              'cv_source': 'ü' * 1_000_000}).encode()
        self.assertGreater(len(payload), request_limits.GENERAL_BODY_BYTES)
        self.assertLess(len(payload), request_limits.PDF_BODY_BYTES)
        status, _, _ = await self.request('/api/jobs/one/documents/finalize', [payload],
                                         app=request_limits.RequestBodyLimitMiddleware(downstream))
        self.assertEqual(status, 200)
        reached.assert_called_once_with(12 * 1024 * 1024, 12 * 1024 * 1024)


class HttpValidationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        patcher = patch.multiple(user_assets, BASE_DIR=str(root), PROFILES_DIR=str(root / 'profiles'))
        patcher.start()
        self.addCleanup(patcher.stop)
        server.app.dependency_overrides[server.get_current_user] = lambda: {'id': 1, 'username': 'fictional'}
        self.addCleanup(server.app.dependency_overrides.clear)
        self.client = TestClient(server.app, base_url='http://127.0.0.1')
        self.addCleanup(self.client.close)

    def test_custom_config_validator_returns_422_json(self):
        for payload in ({'karriere': {'keywords': [{'q': 'x'}]}},
                        {'daily_scraper': {'lanes': [{'keywords': ['x'], 'results_limit': 201}]}}):
            response = self.client.put('/api/config', json=payload)
            self.assertEqual(response.status_code, 422, response.text)
            self.assertIsInstance(response.json()['detail'], list)

    def test_invalid_scrape_cannot_create_a_task(self):
        with patch.object(db, 'async_task_create') as create:
            response = self.client.post('/api/scrape', json={'keywords': 'x', 'results_limit': 501})
        self.assertEqual(response.status_code, 422)
        create.assert_not_called()

    def test_authenticated_login_then_config_round_trip(self):
        server.app.dependency_overrides.clear()
        original = db.DB_PATH
        db.set_db_path(str(Path(self.temp.name) / 'login.db'))
        self.addCleanup(db.set_db_path, original)
        db.init_db()
        db.create_user('fictional', auth.hash_password('fictional-only-password'))
        response = self.client.post('/api/auth/login', json={
            'username': 'fictional', 'password': 'fictional-only-password'})
        self.assertEqual(response.status_code, 200, response.text)
        response = self.client.put('/api/config', json={'linkedin': {'keywords': 'Python'}})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(self.client.get('/api/config').json()['linkedin']['keywords'], 'Python')

    def test_one_million_multibyte_cv_and_notes_remain_supported(self):
        text = '😀' * 1_000_000
        for path, field in (('/api/cv', 'content'), ('/api/profile/notes', 'notes')):
            for ensure_ascii in (True, False):
                response = self.client.put(path, content=json.dumps({field: text}, ensure_ascii=ensure_ascii),
                                           headers={'Content-Type': 'application/json'})
                self.assertEqual(response.status_code, 200, response.text[:200])

    def test_legitimate_pdf_upload_still_reaches_normal_validation(self):
        doc = self.client.post('/api/documents', json={'title': 'Fictional', 'engine': 'typst', 'content': '= CV'})
        self.assertEqual(doc.status_code, 200, doc.text)
        doc_id = doc.json()['id']
        response = self.client.put(f'/api/documents/{doc_id}', json={
            'content': '= CV', 'pdf_base64': base64.b64encode(pdf_bytes()).decode()})
        self.assertEqual(response.status_code, 200, response.text)


class FeedVolumeTest(unittest.TestCase):
    entry = {'name': 'Fictional', 'connector': 'smartrecruiters', 'identifier': 'Fictional'}

    def test_endless_pagination_stops_with_visible_failure(self):
        fetch = Mock(return_value=json.dumps({'content': [{'id': '1'}], 'totalFound': 10**12}))
        with self.assertRaisesRegex(feeds.FeedError, 'pagination'):
            feeds.read_smartrecruiters(self.entry, fetch)
        self.assertEqual(fetch.call_count, feeds.MAX_FEED_PAGES)

    def test_detail_calls_are_bounded_even_with_repeated_ids(self):
        stubs = [{'id': '1', 'name': 'Python', 'location': {'city': 'Vienna'}}] * 201

        def fetch(url, **kwargs):
            return json.dumps({'content': stubs, 'totalFound': len(stubs)}) if '?' in url else '{}'

        calls = Mock(side_effect=fetch)
        with patch.object(feeds, 'MAX_FEED_DETAILS', 2), self.assertRaisesRegex(feeds.FeedError, 'detail'):
            feeds.read_smartrecruiters(self.entry, calls)
        self.assertEqual(calls.call_count, 3)  # One list request and exactly two details.

    def test_company_and_inventory_lists_are_bounded(self):
        with self.assertRaises(feeds.FeedError):
            feeds.fetch_company_postings({'companies': [self.entry] * 51}, fetch=Mock())
        with self.assertRaises(feeds.FeedError):
            feeds.read_greenhouse({'connector': 'greenhouse', 'identifier': 'fictional'},
                                  lambda *a, **kw: json.dumps({'jobs': [{}] * 1001}))

    def test_aggregate_fetch_budget_is_shared_across_companies(self):
        fetch = Mock(return_value=json.dumps({'content': [], 'totalFound': 0}))
        with patch.object(feeds, 'MAX_TOTAL_FEED_REQUESTS', 2):
            rows, errors = feeds.fetch_company_postings({'companies': [self.entry] * 3}, fetch=fetch)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(rows, [])
        self.assertTrue(any('feed requests' in error for error in errors))

    def test_aggregate_row_limit_reports_the_skipped_company(self):
        row = {'id': '1', 'source': 'Company feed', 'job_url': 'https://example.invalid/job',
               'title': 'Python', 'company': 'Fictional', 'location': 'Vienna', 'description': 'A role.'}
        with patch.dict(feeds.READERS, smartrecruiters=lambda *a, **kw: [row]), \
                patch.object(feeds, 'MAX_TOTAL_FEED_ROWS', 1):
            rows, errors = feeds.fetch_company_postings({'companies': [self.entry] * 2}, fetch=Mock())
        self.assertEqual(len(rows), 1)
        self.assertTrue(any('remaining companies skipped' in error for error in errors))
