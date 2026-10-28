"""Operation-wide model ceilings, terminal propagation and real helper cleanup."""
from dataclasses import replace
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import generators
import model_transport as mt
from operation_budget import (Budget, Limits, scope, current, OperationCancelled,
                              OperationDeadline, OperationExhausted, OperationTerminated)
from background_queue import bounded_results
from model_transport_fixture import inline_transport, fictional_ledger


class Reply:
    status_code = 200
    ok = True
    def __init__(self, status=200, message='ok'):
        self.status_code = status
        self.ok = status < 400
        self.data = {'error': {'message': message}} if not self.ok else {'choices': [{'message': {'content': message}}]}
    def json(self):
        return self.data


def budget(**kwargs):
    return Budget(replace(Limits(), **kwargs))


class AllowanceTest(unittest.TestCase):
    def test_custom_both_adjustments_and_retry_share_exact_post_ceiling(self):
        limits = budget(attempts=3)
        replies = [Reply(400, 'max_tokens unsupported'), Reply(400, 'json_schema unsupported'), Reply(500)]
        with scope(budget=limits), inline_transport(), patch.dict(os.environ, CUSTOM_MODEL_BASE_URL='http://localhost/v1'), \
                patch('requests.post', side_effect=replies) as post, patch.object(limits, 'wait'):
            with self.assertRaises(OperationExhausted):
                generators.run_ai_prompt('x', model_name='custom/m', response_format={'json_schema': {'schema': {}}})
        self.assertEqual(post.call_count, 3)
        self.assertEqual(limits.attempts, 3)

    def test_openrouter_schema_fallback_reserves_second_post(self):
        with scope(budget=budget(attempts=1)), inline_transport(), patch.dict(os.environ, OPENROUTER_API_KEY='fictional'), \
                patch('requests.post', return_value=Reply(404)) as post:
            with self.assertRaises(OperationExhausted):
                generators.openrouter_api('x', 'm', response_format={'type': 'json_schema'})
        self.assertEqual(post.call_count, 1)

    def test_expired_cancelled_and_exhausted_do_not_dispatch(self):
        cases = [budget(seconds=.001), Budget(cancelled=lambda: True), budget(attempts=1)]
        cases[0].deadline = 0
        cases[2].reserve(1, 1, 1)
        for shared in cases:
            with self.subTest(shared=shared), fictional_ledger() as ledger, patch.object(mt.subprocess, 'Popen') as launch:
                with self.assertRaises(OperationTerminated), scope(budget=shared):
                    mt.post_json('http://localhost', headers={}, json={'messages': [], 'max_tokens': 1})
                launch.assert_not_called()
                self.assertEqual(ledger.rows, [])

    def test_schema_prompt_and_final_serialized_payload_are_bounded(self):
        with scope(budget=budget(prompt_per_call=5)), inline_transport(), \
                patch.dict(os.environ, CUSTOM_MODEL_BASE_URL='http://localhost'), \
                patch('requests.post', return_value=Reply(400, 'json_schema unsupported')) as post:
            with self.assertRaises(OperationExhausted):
                generators.custom_model_api('x', 'custom/m', response_format={'json_schema': {'schema': {'title': 'large'}}})
        self.assertEqual(post.call_count, 1)
        with scope(budget=budget(payload_per_call=20)), fictional_ledger(), patch.object(mt.subprocess, 'Popen') as launch:
            with self.assertRaises(OperationExhausted):
                mt.post_json('http://localhost', headers={}, json={'messages': [], 'response_format': {'large': 'x' * 30}})
            launch.assert_not_called()

    def test_output_and_aggregate_prompt_allowances_reserve_before_post(self):
        for shared in [budget(output_tokens=7999), budget(prompt_bytes=1)]:
            with scope(budget=shared), inline_transport(), patch('requests.post') as post:
                with self.assertRaises(OperationExhausted):
                    mt.post_json('http://localhost', headers={}, json={'messages': [{'content': 'ab'}], 'max_tokens': 8000})
                post.assert_not_called()

    def test_racing_threads_share_context_and_cannot_overspend(self):
        shared = budget(attempts=3)
        seen = []
        def work(_):
            self.assertIs(current(), shared)
            try:
                current().reserve(1, 1, 1)
                seen.append(1)
            except OperationTerminated:
                return
        with scope(budget=shared):
            # Submit all contenders before one poisons the shared operation.
            from concurrent.futures import ThreadPoolExecutor
            from contextvars import copy_context
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures = [pool.submit(copy_context().run, work, i) for i in range(20)]
                for future in futures: future.result()
        self.assertEqual(len(seen), 3)
        self.assertEqual(shared.attempts, 3)

    def test_bounded_children_inherit_budget_and_stop_replenishment(self):
        shared = budget(attempts=1)
        seen = []
        barrier = threading.Barrier(2)
        failed = threading.Event()
        def work(item):
            self.assertIs(current(), shared)
            seen.append(item)
            barrier.wait(timeout=2)
            try:
                current().reserve(1, 1, 1)
            except OperationTerminated:
                failed.set()
                raise
            failed.wait(2)
        with scope(budget=shared), self.assertRaises(OperationExhausted):
            with bounded_results(work, range(100), 2) as results:
                list(results)
        self.assertLessEqual(len(seen), 2)

    def test_retry_wait_interrupts_cancel_and_deadline(self):
        event = threading.Event()
        shared = Budget(cancelled=event.is_set)
        timer = threading.Timer(.05, event.set)
        timer.start()
        started = time.monotonic()
        with self.assertRaises(OperationCancelled): shared.wait(10)
        timer.join()
        self.assertLess(time.monotonic() - started, .5)
        with self.assertRaises(OperationDeadline): budget(seconds=.05).wait(10)

    def test_provider_retry_wait_obeys_operation_deadline(self):
        with scope(budget=budget(seconds=.05)), patch('generators.openrouter_api', side_effect=RuntimeError('busy')) as post:
            with self.assertRaises(OperationDeadline): generators.run_ai_prompt('x')
        self.assertEqual(post.call_count, 1)

    def test_endpoint_logs_and_errors_omit_url_credentials(self):
        secret_url = 'http://user:fictional-password@localhost/private-token?key=fictional-query'
        with inline_transport(), patch.dict(os.environ, CUSTOM_MODEL_BASE_URL=secret_url, CUSTOM_MODEL_API_KEY='fictional-api-key'), \
                patch('requests.post', return_value=Reply(404, secret_url + ' fictional-api-key')):
            with patch.object(generators.logger, 'info') as logs, self.assertRaises(RuntimeError) as error:
                generators.custom_model_api('x', 'custom/m')
        combined = str(error.exception) + str(logs.call_args_list)
        for secret in (secret_url, 'fictional-password', 'fictional-query', 'fictional-api-key'):
            self.assertNotIn(secret, combined)

    def test_error_credentials_are_redacted_before_display_truncation(self):
        key = 'fictional-long-key-that-crosses-the-display-boundary'
        message = 'x' * 290 + key
        with (inline_transport(), patch.dict(os.environ, CUSTOM_MODEL_BASE_URL='http://localhost', CUSTOM_MODEL_API_KEY=key),
              patch('requests.post', return_value=Reply(404, message))):
            with self.assertRaises(RuntimeError) as error:
                generators.custom_model_api('x', 'custom/m')
        self.assertNotIn(key[:10], str(error.exception))

    def test_ambiguous_transport_error_is_not_retried(self):
        with patch('generators.openrouter_api', side_effect=mt.ModelTransportError('unknown')) as post:
            with self.assertRaises(mt.ModelTransportError): generators.run_ai_prompt('x')
        self.assertEqual(post.call_count, 1)

    def test_document_and_cli_lock_waits_obey_absolute_deadline(self):
        from document_artifacts import document_lock
        import generate_for_job
        import fcntl
        entered, release = threading.Event(), threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            def holder():
                with document_lock(folder):
                    entered.set()
                    release.wait(2)
            thread = threading.Thread(target=holder)
            thread.start()
            self.assertTrue(entered.wait(1))
            try:
                with scope(budget=budget(seconds=.05)), self.assertRaises(OperationDeadline):
                    with document_lock(folder): self.fail('lock acquired after deadline')
            finally:
                release.set()
                thread.join()
            path = Path(folder, 'job.lock')
            with path.open('a') as handle:
                fcntl.flock(handle, fcntl.LOCK_EX)
                with scope(budget=budget(seconds=.05)), self.assertRaises(OperationDeadline):
                    with generate_for_job.job_lock(path): self.fail('CLI lock acquired after deadline')

    def test_injected_document_writer_and_verifier_share_scope(self):
        import reviewed_documents as rd
        shared = budget(attempts=1)
        seen = []
        def run_prompt(*args, **kwargs):
            seen.append(current())
            current().reserve(1, 1, 1)
            return '{"paragraphs": []}'
        with scope(budget=shared), patch.object(rd, 'letter_evidence', return_value={}), \
                patch.object(rd, 'claim_policy', return_value={}), patch.object(rd, 'identity_ids', return_value=set()), \
                patch.object(rd, 'plan_letter', return_value=[]), patch.object(rd, 'letter_prompt', return_value='p'), \
                patch.object(rd, 'verifier_model', return_value='v'), patch.object(rd, 'check_letter', return_value=[]):
            with self.assertRaises(OperationExhausted):
                rd.write_letter({}, {}, None, '', 'writer', run_prompt)
        self.assertEqual(seen, [shared, shared])


class RealHelperTest(unittest.TestCase):
    def invoke(self, code, *, seconds=2, limit=1024):
        """Keep real parent/helper I/O; replace network primitives inside child only."""
        real_popen = subprocess.Popen
        children = []
        def launch(command, **kwargs):
            self.assertNotIn('FICTIONAL_API_KEY', kwargs['env'])
            self.assertNotIn('fictional-secret', ' '.join(command))
            child = real_popen([sys.executable, '-c', code], **kwargs)
            children.append(child)
            return child
        shared = budget(seconds=seconds, response_per_call=limit)
        with patch.dict(os.environ, FICTIONAL_API_KEY='fictional-secret'), fictional_ledger(), \
                patch.object(mt.subprocess, 'Popen', side_effect=launch), scope(budget=shared):
            try:
                return mt.post_json('http://localhost:1234/v1/chat/completions',
                                    headers={'Authorization': 'Bearer fictional-secret'},
                                    json={'messages': [{'content': 'test'}], 'max_tokens': 1})
            finally:
                self.assertTrue(children)
                self.assertIsNotNone(children[0].poll(), 'helper must be reaped before unwinding')

    PRIMITIVES = '''
import model_transport as mt, requests, io, time
class Response:
    status_code = STATUS
    headers = HEADERS
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, chunk_size):
        BODY
class Session:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def post(self, url, **kwargs):
        assert kwargs['allow_redirects'] is False
        assert kwargs['verify'] is True
        assert kwargs['headers']['Accept-Encoding'] == 'identity'
        assert self.trust_env is False
        PRE
        return Response()
requests.Session = Session
mt._worker()
'''
    def code(self, *, status=200, headers=None, body="yield b'{\"choices\": []}'", pre='pass'):
        return self.PRIMITIVES.replace('STATUS', str(status)).replace('HEADERS', repr(headers or {})).replace('BODY', body).replace('PRE', pre)

    def test_default_helper_success_and_local_endpoint(self):
        result = self.invoke(self.code())
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json(), {'choices': []})

    def test_dns_headers_and_trickle_body_deadlines_kill_and_reap(self):
        for phase in ('dns', 'headers', 'body'):
            code = self.code(pre='time.sleep(60)' if phase != 'body' else 'pass',
                             body='while True:\n            time.sleep(.01)\n            yield b"x"')
            started = time.monotonic()
            with self.subTest(phase=phase), self.assertRaises(OperationDeadline):
                self.invoke(code, seconds=.5)
            self.assertGreaterEqual(time.monotonic() - started, .35)
            self.assertLess(time.monotonic() - started, 2)

    def test_cancel_kills_running_helper(self):
        real_popen = subprocess.Popen
        children = []
        def launch(command, **kwargs):
            child = real_popen([sys.executable, '-c', self.code(pre='time.sleep(60)')], **kwargs)
            children.append(child)
            return child
        event = threading.Event()
        timer = threading.Timer(.3, event.set)
        shared = Budget(cancelled=event.is_set)
        timer.start()
        with patch.object(mt.subprocess, 'Popen', side_effect=launch), fictional_ledger(), scope(budget=shared):
            with self.assertRaises(OperationCancelled):
                mt.post_json('http://localhost', headers={}, json={'messages': [], 'max_tokens': 1})
        timer.join()
        self.assertIsNotNone(children[0].poll())

    def test_success_error_encoding_redirect_and_ipc_bounds(self):
        for status in (200, 500):
            with self.subTest(status=status), self.assertRaises(mt.ModelTransportError):
                self.invoke(self.code(status=status, body="yield b'x' * 2048"))
        for code in [self.code(status=307, pre='pass'), self.code(headers={'Content-Encoding': 'gzip'}),
                     'import sys; sys.stdout.write("x" * 100000)',
                     'import sys; sys.stderr.write("x" * 100000)']:
            with self.subTest(code=code[:40]), self.assertRaises(mt.ModelTransportError):
                self.invoke(code)

    def test_real_requests_loopback_only_and_redirect_posts_once(self):
        # The isolated runner's inherited sitecustomize guard continues to deny
        # every external connection. Only this child's chosen loopback is enabled.
        import http.server
        server_posts = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_POST(self):
                server_posts.append(self.path)
                self.rfile.read(int(self.headers['Content-Length']))
                self.send_response(307)
                self.send_header('Location', '/second')
                self.send_header('Content-Length', '0')
                self.end_headers()
            def log_message(self, *args): pass
        with http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever)
            thread.start()
            port = server.server_address[1]
            code = f'''
import socket, _socket, model_transport as mt
blocked = socket.socket.connect
def connect(self, address):
    if address == ('127.0.0.1', {port}): return _socket.socket.connect(self, address)
    return blocked(self, address)
socket.socket.connect = connect
mt._worker()
'''
            real_popen = subprocess.Popen
            def launch(command, **kwargs): return real_popen([sys.executable, '-c', code], **kwargs)
            try:
                with patch.object(mt.subprocess, 'Popen', side_effect=launch), fictional_ledger(), \
                        scope(budget=budget(seconds=3)):
                    with self.assertRaises(mt.ModelTransportError):
                        mt.post_json(f'http://127.0.0.1:{port}/first', headers={}, json={'messages': [], 'max_tokens': 1})
            finally:
                server.shutdown()
                thread.join()
        self.assertEqual(server_posts, ['/first'])




class EntrypointTest(unittest.TestCase):
    def setUp(self):
        import db
        self.db = db
        self.previous = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        db.set_db_path(str(Path(self.temp.name, 'test.db')))
        db.init_db()
        self.user = db.create_user('budget-user', password_hash='fictional')
        import server
        self.server = server

    def tearDown(self):
        self.db.set_db_path(self.previous)
        self.temp.cleanup()

    def test_sync_manual_saves_posting_before_terminal_optional_analysis(self):
        def fail(*args, **kwargs):
            self.assertEqual(len(self.db.load_all_jobs(self.user['id'])), 1)
            self.assertIsNotNone(current())
            raise OperationExhausted('model allowance')
        with patch.object(self.server, 'process_job_with_ai', side_effect=fail), patch.object(self.server, 'load_cv_text', return_value='CV'):
            result = self.server.add_job_manual(self.server.ManualJobRequest(title='Role', company='Example',
                            description='A real posting description'), user=self.user)
        self.assertTrue(result['saved'])
        self.assertFalse(result['success'])
        saved = self.db.get_job_by_id(result['job_id'], self.user['id'])
        self.assertEqual(saved['analysis_state'], 'failed')
        self.assertEqual(saved['raw_description'], 'A real posting description')

    def test_manual_posting_without_a_cv_is_saved_but_not_scored(self):
        with patch.object(self.server, 'process_job_with_ai') as analyse, patch.object(self.server, 'load_cv_text', return_value=''):
            result = self.server.add_job_manual(self.server.ManualJobRequest(title='Role', company='Example',
                            description='A fictional posting description'), user=self.user)
        analyse.assert_not_called()
        self.assertTrue(result['saved'])
        self.assertFalse(result['success'])
        self.assertEqual(result['error'], self.server.NO_CV_MESSAGE)
        saved = self.db.get_job_by_id(result['job_id'], self.user['id'])
        self.assertEqual((saved['analysis_state'], saved['analysis_error']), ('failed', self.server.NO_CV_MESSAGE))

    def test_sync_route_terminates_before_compile_or_publish(self):
        shared = budget()
        def generate(*args, **kwargs):
            self.assertIs(current(), shared)
            raise OperationExhausted('stop')
        self.db.upsert_job({'id': 'a', 'company': 'Example', 'description': 'D'}, user_id=self.user['id'])
        with scope(budget=shared), patch('reviewed_documents.generate', side_effect=generate), \
                patch.object(self.server, 'load_cv_text', return_value='CV'), \
                patch.object(self.server, 'compile_job_document') as compile_doc, \
                patch.object(self.server, 'finalize_job_documents') as publish:
            with self.assertRaises(OperationExhausted):
                self.server.generate_letter(self.server.GenerateRequest(job_id='a'), user=self.user)
        compile_doc.assert_not_called()
        publish.assert_not_called()

    def test_daily_all_lanes_and_retry_use_one_scope(self):
        import daily_scraper as daily
        seen = []
        def scrape(*args, **kwargs):
            seen.append(current())
            current().reserve(1, 1, 1)
        def retry(*args, **kwargs):
            seen.append(current())
            return 0, 0
        config = {'daily_scraper': {'enable_karriere': True, 'karriere': {'keywords': ['a', 'b']},
                                   'lanes': [{'name': 'extra', 'keywords': ['c'], 'source': 'karriere-apify'}]}}
        with patch.object(daily, 'load_config', return_value=config), patch.object(daily, 'load_effective_cv', return_value='CV'), \
                patch.object(daily, 'scrape_new_jobs', side_effect=scrape), patch.object(daily, 'retry_failed_analyses', side_effect=retry):
            daily._run_daily_for_user(self.user)
        self.assertEqual(len(seen), 4)
        self.assertTrue(all(item is seen[0] for item in seen))
        self.assertEqual(seen[0].attempts, 3)
        self.assertIsNone(current())

    def test_daily_terminal_stops_next_lane_and_retry(self):
        import daily_scraper as daily
        config = {'daily_scraper': {'enable_karriere': True, 'karriere': {'keywords': ['a', 'b']}}}
        with patch.object(daily, 'load_config', return_value=config), patch.object(daily, 'load_effective_cv', return_value='CV'), \
                patch.object(daily, 'scrape_new_jobs', side_effect=OperationExhausted('stop')) as scrape, \
                patch.object(daily, 'retry_failed_analyses') as retry:
            with self.assertRaises(OperationExhausted): daily._run_daily_for_user(self.user)
        self.assertEqual(scrape.call_count, 1)
        retry.assert_not_called()

    def test_cli_scope_includes_job_lookup_before_generation(self):
        import generate_for_job
        seen = []
        def lookup(*args):
            seen.append(current())
            return None
        with patch.object(self.db, 'get_user_by_username', side_effect=lookup):
            result, code = generate_for_job.run('missing', 'missing')
        self.assertEqual(code, 2)
        self.assertIsNotNone(seen[0])
        self.assertIsNone(current())

    def test_transport_terminal_failure_is_latched_for_sibling(self):
        shared = budget()
        failed = threading.Event()
        calls = []
        def worker(item):
            if item == 0:
                try:
                    mt.post_json('http://localhost', headers={}, json={'messages': [], 'max_tokens': 1})
                except OperationTerminated:
                    failed.set()
                    raise
            failed.wait(2)
            current().check()
            calls.append('later stage')
        with scope(budget=shared), fictional_ledger(), \
                patch.object(mt, '_supervise', side_effect=mt.ModelTransportError('unknown')):
            with self.assertRaises(mt.ModelTransportError):
                with bounded_results(worker, [0, 1], 2) as results:
                    list(results)
        self.assertEqual(calls, [])

    def test_scoped_cancellation_check_is_removed_after_nested_use(self):
        shared = budget()
        with scope(budget=shared):
            with scope(cancelled=lambda: False): self.assertEqual(len(shared._cancelled), 2)
            self.assertEqual(len(shared._cancelled), 1)

    def test_default_exec_transport_obeys_inherited_external_network_guard(self):
        with scope(budget=budget(seconds=3)), fictional_ledger(), self.assertRaises(mt.ModelTransportError):
            mt.post_json('http://127.0.0.1:9', headers={}, json={'messages': [], 'max_tokens': 1})


if __name__ == '__main__': unittest.main()
