"""Durable model usage ledger, per-User daily quotas and operation attribution.

Fictional users, endpoints and replies only; no network. The supervised helper is
replaced at `_supervise`, so the real ledger, quota and capacity paths run.
"""
import asyncio
import base64
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

from jobweaver import db
from jobweaver import generators
from jobweaver import model_transport as mt
from jobweaver import model_usage
from jobweaver.background_queue import BackgroundQueue, bounded_results
from jobweaver.operation_budget import (AttributionError, Budget, OperationCancelled, OperationDeadline, OperationTerminated,
                              QuotaExceeded, UsageLedgerUnavailable, current, operation, scope)

QUOTA_ENV = (model_usage.ENV_ATTEMPTS, model_usage.ENV_OUTPUT_TOKENS, model_usage.ENV_ZONE)
NOON = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc).timestamp()


def reply(data=None, status=200, raw=None):
    body = raw if raw is not None else json.dumps(data if data is not None else {}).encode()
    return {'status': status, 'body': base64.b64encode(body).decode('ascii')}


def completion(content='fictional answer', **usage):
    data = {'id': 'gen-fictional-1', 'model': 'fictional/served-model',
            'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]}
    if usage:
        data['usage'] = usage
    return data


class LedgerFixture(unittest.TestCase):
    def setUp(self):
        self.previous = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name, 'test.db'))
        db.set_db_path(self.path)
        db.init_db()
        self.alice = db.create_user('alice', password_hash='fictional')
        self.bob = db.create_user('bob', password_hash='fictional')
        self.now = NOON
        environment = {name: value for name, value in os.environ.items() if name not in QUOTA_ENV}
        environment.update({model_usage.ENV_ZONE: 'UTC', 'OPENROUTER_API_KEY': 'fictional-openrouter-key'})
        for patcher in (patch.dict(os.environ, environment, clear=True),
                        patch.object(model_usage, '_clock', lambda: self.now)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        db.set_db_path(self.previous)
        self.temp.cleanup()

    def rows(self, user=None):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            query, params = 'SELECT * FROM model_calls', ()
            if user:
                query, params = query + ' WHERE user_id = ?', (user['id'],)
            return [dict(row) for row in conn.execute(query + ' ORDER BY id', params)]
        finally:
            conn.close()

    def budget(self, user=None, origin='cli', **kwargs):
        return Budget(**kwargs).attribute((user or self.alice)['id'], origin)

    def call(self, *replies, user=None, budget=None, **kwargs):
        """One openrouter_api call in its own attributed operation; returns (result or exception, supervise mock)."""
        shared = budget or self.budget(user)
        effect = replies[0] if len(replies) == 1 and callable(replies[0]) else list(replies)
        with patch.object(mt, '_supervise', side_effect=effect) as supervise, scope(budget=shared):
            try:
                return generators.openrouter_api('fictional prompt', 'fictional/model', 'Letter plan', **kwargs), supervise
            except Exception as exc:
                return exc, supervise


class LedgerFieldsTest(LedgerFixture):
    def test_reservation_and_response_fields_are_stored_exactly(self):
        raw = (b'{"id":"gen-abc.1:x","model":"fictional/served-model","choices":[{"finish_reason":"stop",'
               b'"message":{"content":"fictional answer"}}],"usage":{"prompt_tokens":12,"completion_tokens":5,'
               b'"total_tokens":17,"prompt_tokens_details":{"cached_tokens":3},'
               b'"completion_tokens_details":{"reasoning_tokens":2},"cost":0.000123456789012345678901,"is_byok":false}}')
        shared = self.budget(origin='web')
        result, _ = self.call(reply(raw=raw), budget=shared)
        self.assertEqual(result, 'fictional answer')
        [row] = self.rows()
        payload = json.dumps({'model': 'fictional/model', 'messages': [{'role': 'user', 'content': 'fictional prompt'}],
                              'max_tokens': 8000, 'reasoning': {'max_tokens': 1500}},
                             ensure_ascii=False, separators=(',', ':')).encode()
        expected = dict(user_id=self.alice['id'], origin='web', operation_id=shared.operation_id, task_id=None,
                        purpose='interactive', label='Letter plan', route='openrouter', endpoint_host='openrouter.ai',
                        requested_model='fictional/model', day='2026-10-23', reserved_at='2026-10-23T12:00:00.000Z',
                        prompt_bytes=len(b'fictional prompt'), payload_bytes=len(payload), requested_output_tokens=8000,
                        outcome='responded', finished_at='2026-10-23T12:00:00.000Z', http_status=200,
                        response_bytes=len(raw), provider_request_id='gen-abc.1:x', served_model='fictional/served-model',
                        finish_reason='stop', prompt_tokens=12, completion_tokens=5, total_tokens=17, cached_tokens=3,
                        reasoning_tokens=2, reported_cost='0.000123456789012345678901', cost_unit='openrouter_credits',
                        is_byok=0)
        self.assertEqual({key: row[key] for key in expected}, expected)

    def test_missing_usage_is_null_and_explicit_zero_is_zero_text(self):
        self.call(reply({'choices': [{'message': {'content': 'x'}}]}))
        self.call(reply(completion(cost=0, prompt_tokens=0)))
        self.call(reply(completion(cost=0.0)))
        missing, zero, zero_float = self.rows()
        for column in ('provider_request_id', 'served_model', 'finish_reason', 'prompt_tokens', 'completion_tokens',
                       'total_tokens', 'cached_tokens', 'reasoning_tokens', 'reported_cost', 'cost_unit', 'is_byok'):
            self.assertIsNone(missing[column], column)
        self.assertEqual((zero['reported_cost'], zero['prompt_tokens'], zero['cost_unit']), ('0', 0, 'openrouter_credits'))
        self.assertEqual(zero_float['reported_cost'], '0')

    def test_invalid_values_are_null(self):
        bad = {'id': 'bad id/with spaces', 'model': 'x' * 300,
               'choices': [{'finish_reason': ['stop'], 'message': {'content': 'x'}}],
               'usage': {'prompt_tokens': True, 'completion_tokens': -1, 'total_tokens': 1.5,
                         'prompt_tokens_details': {'cached_tokens': 10 ** 10},
                         'completion_tokens_details': 'many', 'cost': '0.1', 'is_byok': 'no'}}
        self.call(reply(bad))
        self.call(reply(completion(cost=-0.5)))
        self.call(reply(raw=b'{"choices":[{"message":{"content":"x"}}],"usage":{"cost":NaN,"prompt_tokens":"7"}}'))
        self.call(reply(raw=b'{"choices":[{"message":{"content":"x"}}],"usage":{"cost":1e999999}}'))
        first, *others = self.rows()
        for column in ('provider_request_id', 'served_model', 'finish_reason', 'prompt_tokens', 'completion_tokens',
                       'total_tokens', 'cached_tokens', 'reasoning_tokens', 'reported_cost', 'cost_unit', 'is_byok'):
            self.assertIsNone(first[column], column)
        for row in others:
            for column in ('reported_cost', 'cost_unit', 'prompt_tokens'):
                self.assertIsNone(row[column], column)
        self.assertEqual([row['outcome'] for row in self.rows()], ['responded'] * 4)

    def test_truncated_4xx_and_non_json_replies_are_recorded(self):
        truncated = completion(completion_tokens=8000)
        truncated['choices'][0]['finish_reason'] = 'length'
        result, _ = self.call(reply(truncated))
        self.assertIsInstance(result, generators.AITruncatedError)
        result, _ = self.call(reply({'error': {'message': 'fictional refusal'}}, status=401))
        self.assertIsInstance(result, RuntimeError)
        result, _ = self.call(reply(raw=b'<html>fictional gateway</html>', status=502))
        length, refused, gateway = self.rows()
        self.assertEqual((length['finish_reason'], length['completion_tokens']), ('length', 8000))
        self.assertEqual((refused['http_status'], refused['outcome']), (401, 'responded'))
        self.assertEqual((gateway['http_status'], gateway['response_bytes'], gateway['provider_request_id']), (502, 30, None))

    def test_schema_fallback_writes_two_rows(self):
        result, supervise = self.call(reply({'error': {'message': 'none'}}, status=404), reply(completion('{}')),
                                      response_format={'type': 'json_schema'})
        self.assertEqual(result, '{}')
        self.assertEqual(supervise.call_count, 2)
        first, second = self.rows()
        self.assertEqual((first['http_status'], second['http_status']), (404, 200))
        self.assertEqual(first['operation_id'], second['operation_id'])
        self.assertGreater(first['payload_bytes'], second['payload_bytes'])

    def test_transport_error_cancel_and_deadline_are_unknown(self):
        for error in (mt.ModelTransportError('fictional'), OperationCancelled('cancelled'), OperationDeadline('late')):
            with self.subTest(error=type(error).__name__):
                result, _ = self.call(error)
                self.assertIs(result, error)
        rows = self.rows()
        self.assertEqual([row['outcome'] for row in rows], ['unknown'] * 3)
        for row in rows:
            self.assertIsNotNone(row['finished_at'])
            self.assertIsNone(row['http_status'])
            self.assertIsNone(row['reported_cost'])

    def test_locked_ledger_at_update_returns_content_and_row_stays_reserved(self):
        locker = sqlite3.connect(self.path, isolation_level=None)
        def respond(*args):
            locker.execute('BEGIN IMMEDIATE')  # Another writer holds the database while the reply arrives.
            return reply(completion('kept answer', cost=0.5))
        try:
            with patch.object(model_usage, 'FINISH_WAIT', .05), patch.object(model_usage.logger, 'warning') as warning:
                result, _ = self.call(respond)
        finally:
            locker.execute('ROLLBACK')
            locker.close()
        self.assertEqual(result, 'kept answer')
        [row] = self.rows()
        self.assertEqual(row['outcome'], 'reserved')
        self.assertIsNone(row['finished_at'])
        self.assertIsNone(row['reported_cost'])
        warning.assert_called_once()

    def test_locked_ledger_at_reservation_sends_nothing(self):
        locker = sqlite3.connect(self.path, isolation_level=None)
        locker.execute('BEGIN IMMEDIATE')
        shared = self.budget()
        try:
            with patch.object(model_usage, 'LOCK_WAIT', .05):
                result, supervise = self.call(reply(completion()), budget=shared)
        finally:
            locker.execute('ROLLBACK')
            locker.close()
        self.assertIsInstance(result, UsageLedgerUnavailable)
        supervise.assert_not_called()
        self.assertEqual(self.rows(), [])
        with self.assertRaises(UsageLedgerUnavailable):
            shared.check()  # Terminal for the whole operation.
        from jobweaver import server
        response = asyncio.run(server.operation_terminal_response(None, result))
        self.assertEqual(response.status_code, 503)

    def test_unexpected_parse_failure_still_returns_response(self):
        with patch.object(model_usage, '_response_fields', side_effect=RuntimeError('fictional')):
            result, _ = self.call(reply(completion('kept', cost=1)))
        self.assertEqual(result, 'kept')
        [row] = self.rows()
        self.assertEqual((row['outcome'], row['http_status'], row['reported_cost']), ('responded', None, None))
        self.assertIsNotNone(row['finished_at'])

    def test_missing_owner_is_refused_as_attribution_not_busy(self):
        shared = Budget().attribute(999999, 'cli')
        result, supervise = self.call(reply(completion()), budget=shared)
        self.assertIsInstance(result, AttributionError)
        self.assertNotIsInstance(result, UsageLedgerUnavailable)
        self.assertNotIn('busy', str(result))
        supervise.assert_not_called()
        self.assertEqual(self.rows(), [])
        from jobweaver import server
        self.assertEqual(asyncio.run(server.operation_terminal_response(None, result)).status_code, 502)

    def test_retention_prunes_rows_older_than_400_days_at_backend_start(self):
        self.now = NOON - 401 * 86400
        self.call(reply(completion()))
        self.now = NOON - 399 * 86400
        self.call(reply(completion()))
        self.now = NOON
        queue = BackgroundQueue()
        queue.start()
        queue.close()
        self.assertEqual([row['reserved_at'][:10] for row in self.rows()], ['2025-09-19'])
        self.assertEqual(model_usage.prune(), 0)

    def test_privacy_no_prompt_url_query_userinfo_key_or_response_in_any_column(self):
        secrets = ['fictional-secret-prompt', 'fictional-pass', 'fictional-user', 'fictional-query', 'fictional-custom-key',
                   'fictional-openrouter-key', 'fictional-secret-answer', 'fictional-error-body', '/v1', 'http', '?', '@']
        base = 'http://fictional-user:fictional-pass@models.example.test:8080/v1?token=fictional-query'
        replies = [reply(completion('fictional-secret-answer', prompt_tokens=1)),
                   reply({'error': {'message': 'fictional-error-body ' + base}}, status=403)]
        with patch.dict(os.environ, CUSTOM_MODEL_BASE_URL=base, CUSTOM_MODEL_API_KEY='fictional-custom-key'), \
                patch.object(mt, '_supervise', side_effect=replies), scope(budget=self.budget()):
            generators.custom_model_api('fictional-secret-prompt', 'custom/fictional-local', 'sonar-Acme Bank GmbH')
            with self.assertRaises(RuntimeError):
                generators.custom_model_api('fictional-secret-prompt', 'custom/fictional-local', 'ProbeTag [alice]')
        rows = self.rows()
        self.assertEqual([(row['route'], row['endpoint_host']) for row in rows], [('custom', 'models.example.test')] * 2)
        self.assertEqual([row['label'] for row in rows], ['model', 'model'])  # Only fixed code labels are stored.
        secrets += ['Acme', 'Bank', 'ProbeTag', 'alice', 'sonar']
        for row in rows:
            for column, value in row.items():
                for secret in secrets:
                    self.assertNotIn(secret, str(value), f'{column} leaks {secret!r}')

    def test_custom_endpoint_cost_unit_only_when_stated(self):
        with patch.dict(os.environ, CUSTOM_MODEL_BASE_URL='http://localhost:11434/v1'), \
                patch.object(mt, '_supervise', side_effect=[reply(completion(prompt_tokens=4)), reply(completion(cost=2))]), \
                scope(budget=self.budget()):
            generators.custom_model_api('x', 'custom/m')
            generators.custom_model_api('x', 'custom/m')
        plain, costed = self.rows()
        self.assertEqual((plain['route'], plain['reported_cost'], plain['cost_unit']), ('custom', None, None))
        self.assertEqual((costed['reported_cost'], costed['cost_unit']), ('2', 'endpoint_reported'))


class QuotaTest(LedgerFixture):
    def test_under_and_at_attempt_limit_refuses_without_dispatch_or_row(self):
        model_usage.set_quota(self.alice['id'], attempts=2)
        self.now = datetime(2026, 10, 23, 23, 59, 0, tzinfo=timezone.utc).timestamp()
        for _ in range(2):
            result, _ = self.call(reply(completion()))
            self.assertEqual(result, 'fictional answer')
        result, supervise = self.call(reply(completion()))
        self.assertIsInstance(result, QuotaExceeded)
        supervise.assert_not_called()
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(result.retry_after, 60)
        self.assertIn('requests', str(result))
        self.assertNotIn('spend', str(result).lower())
        from jobweaver import server
        response = asyncio.run(server.operation_terminal_response(None, result))
        self.assertEqual((response.status_code, response.headers['Retry-After']), (429, '60'))

    def test_requested_output_token_quota(self):
        model_usage.set_quota(self.alice['id'], output_tokens=10000)
        self.assertEqual(self.call(reply(completion()))[0], 'fictional answer')
        result, supervise = self.call(reply(completion()))
        self.assertIsInstance(result, QuotaExceeded)
        self.assertIn('requested output tokens', str(result))
        supervise.assert_not_called()
        self.assertEqual(len(self.rows()), 1)

    def test_attempts_are_never_refunded(self):
        model_usage.set_quota(self.alice['id'], attempts=2)
        self.call(mt.ModelTransportError('fictional'))
        self.call(reply({'error': {'message': 'fictional'}}, status=500))
        result, supervise = self.call(reply(completion()))
        self.assertIsInstance(result, QuotaExceeded)
        supervise.assert_not_called()
        self.assertEqual([row['outcome'] for row in self.rows()], ['unknown', 'responded'])

    def test_per_user_isolation_and_day_rollover(self):
        model_usage.set_quota(self.alice['id'], attempts=1)
        self.assertEqual(self.call(reply(completion()))[0], 'fictional answer')
        self.assertIsInstance(self.call(reply(completion()))[0], QuotaExceeded)
        self.assertEqual(self.call(reply(completion()), user=self.bob)[0], 'fictional answer')
        self.now += 12 * 3600  # Midnight UTC passed.
        self.assertEqual(self.call(reply(completion()))[0], 'fictional answer')
        self.assertEqual([row['day'] for row in self.rows(self.alice)], ['2026-10-23', '2026-10-24'])

    def test_quota_day_follows_configured_zone(self):
        # 23.10.2026 22:30 UTC is already 24.10.2026 00:30 in Vienna (CEST, UTC+2).
        moment = datetime(2026, 10, 23, 22, 30, tzinfo=timezone.utc).timestamp()
        from zoneinfo import ZoneInfo
        self.assertEqual(model_usage.quota_day(moment, ZoneInfo('Europe/Vienna')), ('2026-10-24', 84600))
        self.assertEqual(model_usage.quota_day(moment, ZoneInfo('UTC')), ('2026-10-23', 5400))

    def test_child_threads_share_one_budget_and_quota(self):
        model_usage.set_quota(self.alice['id'], attempts=3)
        shared = self.budget()
        def work(item):
            return generators.openrouter_api('x', 'fictional/model')
        with patch.object(mt, '_supervise', side_effect=lambda *args: reply(completion())), scope(budget=shared):
            with bounded_results(work, range(3), 3) as results:
                self.assertEqual(list(results), ['fictional answer'] * 3)
        rows = self.rows()
        self.assertEqual(len(rows), 3)
        self.assertEqual({row['operation_id'] for row in rows}, {shared.operation_id})
        self.assertEqual(shared.attempts, 3)

    def test_quota_refusal_stops_sibling_stages(self):
        model_usage.set_quota(self.alice['id'], attempts=1)
        self.call(reply(completion()))
        refused, later = threading.Event(), []
        def worker(item):
            if item == 0:
                try:
                    generators.openrouter_api('x', 'fictional/model')
                except QuotaExceeded:
                    refused.set()
                    raise
            refused.wait(2)
            current().check()
            later.append(item)
        with patch.object(mt, '_supervise', side_effect=lambda *args: reply(completion())), \
                scope(budget=self.budget()), self.assertRaises(QuotaExceeded):
            with bounded_results(worker, [0, 1], 2) as results:
                list(results)
        self.assertEqual(later, [])

    def test_real_processes_racing_at_limit_write_exactly_limit_rows(self):
        limit, processes, calls = 5, 4, 3
        model_usage.set_quota(self.alice['id'], attempts=limit)
        start = Path(self.temp.name, 'start')
        code = r'''
import os, sys, time
from pathlib import Path
from jobweaver import db
db.set_db_path(sys.argv[1])
from jobweaver import model_transport as mt
from jobweaver.operation_budget import Budget, scope, QuotaExceeded
class Reply:
    status_code = 200
    content = b'{"choices":[{"message":{"content":"x"}}]}'
mt._post_impl = lambda *args, **kwargs: Reply()
while not Path(sys.argv[2]).exists():
    time.sleep(.005)
sent = 0
for _ in range(int(sys.argv[4])):
    try:
        with scope(budget=Budget().attribute(int(sys.argv[3]), 'cli')):
            mt.post_json('https://openrouter.ai/api/v1/chat/completions', headers={},
                         json={'model': 'm', 'messages': [], 'max_tokens': 10})
        sent += 1
    except QuotaExceeded:
        pass
print(sent)
'''
        children = [subprocess.Popen([sys.executable, '-c', code, self.path, str(start), str(self.alice['id']), str(calls)],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                    for _ in range(processes)]
        start.touch()
        outputs = [child.communicate(timeout=60) for child in children]
        self.assertEqual([child.returncode for child in children], [0] * processes, [err for _, err in outputs])
        self.assertEqual(sum(int(out) for out, _ in outputs), limit)
        self.assertEqual(len(self.rows()), limit)

    def test_invalid_environment_is_rejected(self):
        for name in (model_usage.ENV_ATTEMPTS, model_usage.ENV_OUTPUT_TOKENS):
            for value in ('0', '-1', 'abc', '1.5', '١٢', '10000000000'):
                with self.subTest(name=name, value=value), self.assertRaises(model_usage.QuotaSettingsError):
                    model_usage.settings({name: value})
        with self.assertRaises(model_usage.QuotaSettingsError):
            model_usage.settings({model_usage.ENV_ZONE: 'Fictional/Nowhere'})
        self.assertEqual(model_usage.settings({}).attempts, 300)
        self.assertEqual(model_usage.settings({}).output_tokens, 2_400_000)
        self.assertEqual(model_usage.settings({model_usage.ENV_ATTEMPTS: ' 12 '}).attempts, 12)
        with patch.dict(os.environ, {model_usage.ENV_ATTEMPTS: '0'}):
            result, supervise = self.call(reply(completion()))
        self.assertIsInstance(result, model_usage.QuotaSettingsError)
        supervise.assert_not_called()
        self.assertEqual(self.rows(), [])
        env = {key: value for key, value in os.environ.items()}
        env[model_usage.ENV_ATTEMPTS] = 'abc'
        startup = subprocess.run([sys.executable, '-c', 'from jobweaver import daily_scraper; daily_scraper.run_daily_scraping()'],
                                 env=env, capture_output=True, text=True, timeout=60)
        self.assertNotEqual(startup.returncode, 0)
        self.assertIn(model_usage.ENV_ATTEMPTS, startup.stderr)

    def test_environment_defaults_apply_without_override(self):
        with patch.dict(os.environ, {model_usage.ENV_ATTEMPTS: '1'}):
            self.call(reply(completion()))
            self.assertIsInstance(self.call(reply(completion()))[0], QuotaExceeded)
        self.assertEqual(model_usage.quota_status(self.alice['id'])['requests_limit'], 300)


class AdministrationTest(LedgerFixture):
    def run_admin(self, *argv):
        from jobweaver import manage_users
        output = io.StringIO()
        with redirect_stdout(output), redirect_stderr(io.StringIO()):
            code = manage_users.main(list(argv))
        return code, output.getvalue()

    def test_manage_users_override_default_and_usage_coverage(self):
        code, text = self.run_admin('quota', 'alice', '--attempts', '7', '--output-tokens', '64000')
        self.assertEqual(code, 0)
        self.assertIn('per-user override', text)
        status = model_usage.quota_status(self.alice['id'])
        self.assertEqual((status['requests_limit'], status['requested_output_tokens_limit']), (7, 64000))
        self.run_admin('quota', 'alice', '--attempts', '9')
        self.assertEqual(model_usage.quota_status(self.alice['id'])['requested_output_tokens_limit'], 64000)
        code, text = self.run_admin('quota', 'alice', '--default')
        self.assertEqual(code, 0)
        self.assertIn('server default', text)
        self.assertFalse(model_usage.quota_status(self.alice['id'])['override'])
        with self.assertRaises(SystemExit):
            self.run_admin('quota', 'alice', '--attempts', '0')
        self.assertEqual(self.run_admin('quota', 'nobody')[0], 1)

        self.call(reply(completion(cost=0.25)))
        self.call(reply(completion()))
        self.call(mt.ModelTransportError('fictional'))
        report = model_usage.usage_report(self.alice['id'])
        self.assertEqual(report[0]['reported_cost'], {'openrouter_credits': '0.25'})
        self.assertEqual((report[0]['rows'], report[0]['rows_with_cost'], report[0]['rows_without_cost'],
                          report[0]['without_response'], report[0]['unknown']), (3, 1, 2, 1, 1))
        code, text = self.run_admin('usage', 'alice', '--day', '2026-10-23')
        self.assertEqual(code, 0)
        self.assertIn('0.25 openrouter_credits over 1 of 3 rows', text)
        self.assertIn('2 rows have no reported cost (unknown, not zero)', text)
        self.assertIn('No model requests recorded', self.run_admin('usage', '--day', '2026-10-22')[1])
        for day in ('23.10.2026', '2026-W43-5', '20261023', '2026-02-30'):
            with self.subTest(day=day), self.assertRaises(SystemExit):
                self.run_admin('usage', '--day', day)

    def test_manage_users_loads_dotenv_quota_settings(self):
        from jobweaver import manage_users
        def load():
            os.environ[model_usage.ENV_ATTEMPTS] = '17'
        with patch.object(manage_users, 'load_dotenv', side_effect=load) as loaded:
            code, text = self.run_admin('quota', 'alice')
        loaded.assert_called_once()
        self.assertEqual(code, 0)
        self.assertIn('0 of 17', text)

    def test_put_config_cannot_change_quotas(self):
        from jobweaver import server
        from jobweaver import user_assets
        with patch.multiple(user_assets, BASE_DIR=self.temp.name, PROFILES_DIR=str(Path(self.temp.name, 'profiles'))):
            server.save_config(body={'daily_attempts': 999999, 'model_quotas': {'attempts': 999999},
                                     'user_model_quotas': {'daily_output_tokens': 1}}, user=self.alice)
        status = model_usage.quota_status(self.alice['id'])
        self.assertEqual((status['requests_limit'], status['requested_output_tokens_limit'], status['override']),
                         (300, 2_400_000, False))

    def test_usage_today_route_is_scoped_to_signed_in_user(self):
        from jobweaver import server
        self.call(reply(completion(cost=1)))
        self.call(reply(completion()), user=self.bob)
        status = server.usage_today(user=self.alice)
        self.assertEqual((status['requests_used'], status['requests_limit'], status['monetary_ceiling']), (1, 300, False))
        self.assertEqual(status['coverage']['reported_cost'], {'openrouter_credits': '1'})
        self.assertEqual(server.usage_today(user=db.get_user_by_username('admin'))['coverage'], None)

    def test_delete_user_removes_ledger_and_quota_rows(self):
        model_usage.set_quota(self.alice['id'], attempts=5)
        model_usage.set_quota(self.bob['id'], attempts=6)
        self.call(reply(completion()))
        self.call(reply(completion()), user=self.bob)
        db.delete_user(self.alice['id'])
        self.assertEqual(self.rows(self.alice), [])
        self.assertEqual(len(self.rows(self.bob)), 1)
        conn = sqlite3.connect(self.path)
        try:
            owners = [row[0] for row in conn.execute('SELECT user_id FROM user_model_quotas')]
        finally:
            conn.close()
        self.assertEqual(owners, [self.bob['id']])

    def test_migration_is_additive_and_init_db_twice_is_harmless(self):
        db.upsert_job({'id': 'li_1', 'job_url': 'https://example.com/job/1', 'title': 'Role', 'company': 'Example'},
                      user_id=self.alice['id'])
        conn = sqlite3.connect(self.path)
        conn.execute('DROP TABLE model_calls')
        conn.execute('DROP TABLE user_model_quotas')
        conn.commit()
        def snapshot():
            conn = sqlite3.connect(self.path)
            try:
                return {table: conn.execute(f'SELECT * FROM {table} ORDER BY 1').fetchall()
                        for table in ('users', 'jobs', 'user_sessions', 'async_tasks', 'retired_usernames')}
            finally:
                conn.close()
        conn.close()
        before = snapshot()
        db.init_db()
        self.assertEqual(snapshot(), before)
        self.call(reply(completion()))
        ledger = self.rows()
        db.init_db()
        self.assertEqual(self.rows(), ledger)
        self.assertEqual(snapshot(), before)

    def test_ledger_tables_are_created_on_first_use_without_init_db(self):
        conn = sqlite3.connect(self.path)
        conn.execute('DROP TABLE model_calls')
        conn.execute('DROP TABLE user_model_quotas')
        conn.commit()
        conn.close()
        self.assertEqual(self.call(reply(completion()))[0], 'fictional answer')
        self.assertEqual(len(self.rows()), 1)


class AttributionTest(LedgerFixture):
    def test_unattributed_operation_fails_closed_without_dispatch(self):
        shared = Budget()
        with patch.object(mt, '_supervise') as supervise, patch('jobweaver.capacity.acquire') as acquire, scope(budget=shared):
            with self.assertRaises(AttributionError):
                generators.openrouter_api('x', 'fictional/model')
        supervise.assert_not_called()
        acquire.assert_not_called()
        self.assertEqual(self.rows(), [])
        self.assertEqual(shared.attempts, 0)

    def test_attribution_is_set_once(self):
        shared = Budget().attribute(self.alice['id'], 'web')
        shared.attribute(self.alice['id'], 'background', task_id='t-1')
        self.assertEqual((shared.owner, shared.origin, shared.task_id), (self.alice['id'], 'web', 't-1'))
        with self.assertRaises(AttributionError):
            shared.attribute(self.bob['id'], 'web')
        with self.assertRaises(AttributionError):
            shared.check()  # Latched for sibling stages.
        for owner, origin in ((True, 'web'), (0, 'web'), ('1', 'web'), (1, 'mcp')):
            with self.assertRaises(ValueError):
                Budget().attribute(owner, origin)

    def test_operation_decorator_attributes_only_a_new_operation(self):
        seen = []
        @operation()
        def route(req, user=None):
            seen.append((current().owner, current().origin))
        route(None, user=self.alice)
        route(None, user={'username': 'no id'})
        with scope(budget=Budget()):
            route(None, user=self.alice)  # Nested: the outer operation stays unattributed.
        self.assertEqual(seen, [(self.alice['id'], 'web'), (None, None), (None, None)])

    def test_web_route_attributes_signed_in_user(self):
        from jobweaver import server
        db.upsert_job({'id': 'job-1', 'job_url': 'https://example.com/job/1', 'company': 'Example AG', 'title': 'Role'},
                      user_id=self.bob['id'])
        with patch.object(mt, '_supervise', side_effect=[reply(completion('fictional research'))]):
            server.research_job_company('job-1', None, user=self.bob)
        [row] = self.rows()
        self.assertEqual((row['user_id'], row['origin'], row['task_id'], row['label']),
                         (self.bob['id'], 'web', None, 'Company research'))
        for value in row.values():
            self.assertNotIn('Example', str(value))

    def test_background_queue_attributes_owner_and_task(self):
        queue = BackgroundQueue()
        queue.start()
        done = threading.Event()
        def callback(task_id):
            try:
                generators.openrouter_api('x', 'fictional/model')
            finally:
                done.set()
        try:
            with patch.object(mt, '_supervise', side_effect=lambda *args: reply(completion())):
                task = queue.submit('scrape', self.bob['id'], {'fictional': True}, callback)
                self.assertTrue(done.wait(10))
        finally:
            queue.close()
        [row] = self.rows()
        self.assertEqual((row['user_id'], row['origin'], row['task_id'], row['purpose']),
                         (self.bob['id'], 'background', task['task_id'], 'collection'))

    def test_daily_run_attributes_each_user_and_quota_refusal_continues(self):
        from jobweaver import daily_scraper as daily
        model_usage.set_quota(self.alice['id'], attempts=1)
        self.call(reply(completion()))  # Alice is already at her quota.
        seen = []
        def scrape(*args, **kwargs):
            seen.append((current().owner, current().origin, current().purpose))
            generators.openrouter_api('x', 'fictional/model')
        config = {'daily_scraper': {'enable_karriere': True, 'karriere': {'keywords': ['a']}}}
        with patch.object(daily, 'load_config', return_value=config), patch.object(daily, 'load_effective_cv', return_value='CV'), \
                patch.object(daily, 'scrape_new_jobs', side_effect=scrape), \
                patch.object(daily, 'retry_failed_analyses', return_value=(0, 0)), \
                patch.object(daily.db, 'list_users', return_value=[self.alice, self.bob]), \
                patch.object(mt, '_supervise', side_effect=lambda *args: reply(completion())), \
                patch.object(daily.logger, 'warning') as warning:
            daily.run_daily_scraping()
        self.assertEqual(seen, [(self.alice['id'], 'scheduled', 'collection'), (self.bob['id'], 'scheduled', 'collection')])
        self.assertTrue(any('stopped' in str(call) for call in warning.call_args_list))
        self.assertEqual([(row['user_id'], row['origin']) for row in self.rows(self.bob)], [(self.bob['id'], 'scheduled')])

    def test_cli_attributes_after_user_lookup_and_reports_quota(self):
        from jobweaver import generate_for_job
        seen = []
        def lookup(job_id, user_id):
            seen.append((current().owner, current().origin, current().purpose))
            raise QuotaExceeded('Daily model request quota reached: fictional.', 42)
        output = io.StringIO()
        with patch.object(db, 'get_job_by_id', side_effect=lookup), redirect_stdout(output):
            code = generate_for_job.main(['--user', 'alice', '--job', 'job-1'])
        self.assertEqual(seen, [(self.alice['id'], 'cli', 'documents')])
        self.assertEqual(code, 1)
        result = json.loads(output.getvalue())
        self.assertEqual((result['ok'], result['retry_after_seconds']), (False, 42))
        self.assertIn('quota', result['errors'][0])

    def test_model_helper_script_never_loads_database_or_dotenv(self):
        code = ('import runpy, sys\nsys.argv = ["model_transport", "--worker"]\n'
                'runpy.run_module("jobweaver.model_transport", run_name="__main__")\n'
                'print(sorted(name for name in ("jobweaver.db", "dotenv", "jobweaver.model_usage", "pandas") if name in sys.modules), '
                'file=sys.stderr)')
        # -S keeps the isolated runner's sitecustomize (which imports dotenv) out of the measurement.
        result = subprocess.run([sys.executable, '-S', '-c', code], input=b'not-a-deadline\n', capture_output=True,
                                cwd=str(Path(mt.__file__).parents[1]), timeout=30)
        self.assertEqual(result.stdout, b'{"error":"ValueError"}')
        self.assertEqual(result.stderr.strip(), b'[]')


if __name__ == '__main__':
    unittest.main()
