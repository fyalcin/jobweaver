"""Disposable operation admission, cancellation and startup ownership checks."""
from concurrent.futures import ThreadPoolExecutor
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from jobweaver import db
from jobweaver import server
from jobweaver.background_queue import BackgroundQueue, bounded_results


class QueueFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = db.DB_PATH
        db.set_db_path(os.path.join(self.temp.name, 'test.db'))
        db.init_db()
        self.user = db.get_user_by_username('admin')
        self.other = db.create_user('other', password_hash='x')
        self.release = threading.Event()
        self.queue = BackgroundQueue()
        self.queue.start()

    def tearDown(self):
        self.release.set()
        self.queue.close()
        db.set_db_path(self.old_path)
        self.temp.cleanup()

    def blocked(self, started=None):
        def callback(task_id):
            if started:
                started.set()
            if not self.release.wait(10):
                raise TimeoutError('Test did not release callback')
        return callback

    def submit(self, payload=None, *, user=None, kind='scrape', callback=None):
        return self.queue.submit(kind, (user or self.user)['id'], payload or {},
                                 callback or self.blocked())

    def row(self, response, user=None):
        return db.async_task_get(response['task_id'], (user or self.user)['id'])

    def wait_status(self, response, expected, user=None):
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            row = self.row(response, user)
            if row['status'] == expected:
                return row
            time.sleep(.005)
        self.fail(f'Expected {expected}, got {row}')


class BackgroundQueueTest(QueueFixture):
    def test_duplicate_race_invokes_one_callback_and_is_user_scoped(self):
        barrier = threading.Barrier(12)
        called = []
        def callback(task_id):
            called.append(task_id)
            self.blocked()(task_id)
        def start(_):
            barrier.wait(5)
            return self.submit({'same': ['input']}, callback=callback)
        with ThreadPoolExecutor(max_workers=12) as pool:
            responses = list(pool.map(start, range(12)))
        self.assertEqual(len({r['task_id'] for r in responses}), 1)
        self.assertEqual(sum(not r['reused'] for r in responses), 1)
        self.assertEqual(len(called), 1)
        other = self.submit({'same': ['input']}, user=self.other)
        self.assertNotEqual(other['task_id'], responses[0]['task_id'])
        self.assertIsNone(db.async_task_get(responses[0]['task_id'], self.other['id']))

    def test_global_waiting_and_per_user_capacity_with_eligible_fifo(self):
        first = self.submit({'n': 1})
        own_waiter = self.submit({'n': 2})
        self.assertEqual(self.row(own_waiter)['status'], 'queued')
        with self.assertRaises(db.TaskCapacityError):
            self.submit({'n': 3})
        # Another User can use the idle global slot despite the first User's waiter.
        second = self.submit(user=self.other)
        self.assertEqual(self.row(second, self.other)['status'], 'running')
        waiting = [own_waiter]
        for i in range(7):
            user = db.create_user(f'waiter{i}', password_hash='x')
            waiting.append(self.submit(user=user))
        extra = db.create_user('excess', password_hash='x')
        with self.assertRaises(db.TaskCapacityError):
            self.submit(user=extra)
        self.assertEqual(sum(op.thread is None for op in self.queue._operations.values()), 8)
        self.assertEqual(len(self.queue._operations), 10)
        self.queue.cancel(self.user['id'], task_id=first['task_id'])
        self.assertEqual(self.row(own_waiter)['status'], 'queued')
        self.release.set()
        self.wait_status(own_waiter, 'completed')

    def test_running_cancel_retains_capacity_and_duplicate_until_exit(self):
        started = threading.Event()
        first = self.submit(callback=self.blocked(started))
        self.assertTrue(started.wait(5))
        self.queue.cancel(self.user['id'], task_id=first['task_id'])
        row = self.row(first)
        self.assertEqual((row['status'], row['stage']), ('running', 'cancelling'))
        duplicate = self.submit()
        self.assertEqual(first['task_id'], duplicate['task_id'])
        self.assertTrue(duplicate['reused'])
        queued = self.submit({'next': True})
        self.assertEqual(self.row(queued)['status'], 'queued')
        self.release.set()
        self.wait_status(first, 'cancelled')
        self.wait_status(queued, 'completed')

    def test_queued_cancel_never_runs_callback_and_releases_slot(self):
        self.submit()
        called = threading.Event()
        queued = self.submit({'queued': True}, callback=lambda tid: called.set())
        self.assertEqual(db.async_task_get_latest_running_scrape(self.user['id'])[0], queued['task_id'])
        self.assertEqual(self.queue.cancel(self.other['id'], task_id=queued['task_id']), 0)
        self.queue.cancel(self.user['id'], task_id=queued['task_id'])
        self.assertEqual(self.row(queued)['status'], 'cancelled')
        self.submit({'replacement': True})
        self.release.set()
        self.queue.close()
        self.assertFalse(called.is_set())

    def test_worker_error_releases_capacity_and_runs_next(self):
        entered, crash = threading.Event(), threading.Event()
        def callback(task_id):
            entered.set()
            if not crash.wait(5):
                raise TimeoutError('Missing crash trigger')
            raise ValueError('fictional worker failure')
        first = self.submit(callback=callback)
        self.assertTrue(entered.wait(5))
        second = self.submit({'next': True}, callback=lambda tid: None)
        crash.set()
        failed = self.wait_status(first, 'failed')
        self.assertIn('fictional worker failure', failed['result']['message'])
        self.wait_status(second, 'completed')

    def test_thread_start_failure_frees_reservation_for_retry(self):
        with patch('jobweaver.background_queue.threading.Thread.start', side_effect=RuntimeError('thread unavailable')):
            failed = self.submit()
        self.assertEqual(self.row(failed)['status'], 'failed')
        self.assertFalse(self.queue._operations)
        retried = self.submit()
        self.assertNotEqual(failed['task_id'], retried['task_id'])
        self.assertEqual(self.row(retried)['status'], 'running')

    def test_fifo_skips_ineligible_user_without_starving_eligible_waiter(self):
        self.submit()
        free_second = threading.Event()
        second = self.submit(user=self.other, callback=lambda tid: free_second.wait(5))
        older_ineligible = self.submit({'older': True})
        third = db.create_user('eligible', password_hash='x')
        started = threading.Event()
        eligible = self.submit(user=third, callback=lambda tid: started.set())
        self.assertEqual(self.row(eligible, third)['status'], 'queued')
        free_second.set()
        self.assertTrue(started.wait(5))
        self.wait_status(second, 'completed', self.other)
        self.assertEqual(self.row(older_ineligible)['status'], 'queued')

    def test_shutdown_retains_owner_until_running_callback_exits(self):
        started = threading.Event()
        self.submit(callback=self.blocked(started))
        self.assertTrue(started.wait(5))
        with ThreadPoolExecutor(max_workers=1) as pool:
            closing = pool.submit(self.queue.close)
            with self.assertRaises(BlockingIOError):
                BackgroundQueue().start()
            self.assertFalse(closing.done())
            self.release.set()
            closing.result(5)
        replacement = BackgroundQueue()
        replacement.start()
        replacement.close()

    def test_terminal_callback_write_does_not_release_capacity_early(self):
        written = threading.Event()
        def callback(task_id):
            db.async_task_update(task_id, status='completed')
            written.set()
            self.blocked()(task_id)
        first = self.submit(callback=callback)
        self.assertTrue(written.wait(5))
        self.assertEqual(self.submit()['task_id'], first['task_id'])
        queued = self.submit({'different': True})
        self.assertEqual(self.row(queued)['status'], 'queued')

    def test_owner_lock_refuses_another_process_before_recovery(self):
        first = self.submit()
        code = """import sys; from jobweaver import db
from jobweaver.background_queue import BackgroundQueue
db.set_db_path(sys.argv[1])
try:
    BackgroundQueue().start()
except BlockingIOError:
    raise SystemExit(23)
raise SystemExit(99)
"""
        result = subprocess.run([sys.executable, '-c', code, db.DB_PATH], capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 23, result.stderr.decode())
        self.assertEqual(self.row(first)['status'], 'running')
        self.assertEqual(self.row(first)['stage'], 'running')

    def test_owned_restart_interrupts_queued_and_running_without_replay(self):
        self.queue.close()
        for task_id, status in [('old-running', 'running'), ('old-queued', 'queued')]:
            db.async_task_create(task_id, 'scrape', user_id=self.user['id'])
            db.async_task_update(task_id, status=status)
        self.queue.start()
        for task_id in ('old-running', 'old-queued'):
            row = db.async_task_get(task_id, self.user['id'])
            self.assertEqual((row['status'], row['stage']), ('interrupted', 'interrupted'))
            self.assertIn('Retry explicitly', row['result']['message'])
        self.assertFalse(self.queue._operations)
        self.assertFalse(self.submit()['reused'])

    def test_child_submission_is_bounded_and_cancel_drains_calls(self):
        pulled, entered = [], threading.Barrier(3)
        stop = threading.Event()
        def items():
            for i in range(1000):
                pulled.append(i)
                yield i
        def child(i):
            entered.wait(5)
            if not self.release.wait(5):
                raise TimeoutError('Missing child release')
            return i
        def run():
            with bounded_results(child, items(), 2, cancelled=stop.is_set) as results:
                return list(results)
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(run)
            entered.wait(5)
            self.assertEqual(pulled, [0, 1])
            stop.set()
            self.assertFalse(future.done())
            self.release.set()
            self.assertEqual(sorted(future.result(5)), [0, 1])

    def test_early_consumer_exit_drains_running_child_without_gc(self):
        child_started, consumer_exited = threading.Event(), threading.Event()
        def child(i):
            if i:
                child_started.set()
                if not self.release.wait(5):
                    raise TimeoutError('Missing child release')
            else:
                if not child_started.wait(5):
                    raise TimeoutError('Child did not start')
            return i
        def consume():
            with bounded_results(child, range(1000), 2) as results:
                for result in results:
                    self.assertEqual(result, 0)
                    consumer_exited.set()
                    break
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(consume)
            self.assertTrue(consumer_exited.wait(5))
            self.assertFalse(future.done())
            self.release.set()
            future.result(5)


class BackgroundHTTPTest(QueueFixture):
    def setUp(self):
        super().setUp()
        self.old_queue = getattr(server.app.state, 'background_queue', None)
        server.app.state.background_queue = self.queue
        server.app.dependency_overrides[server.get_current_user] = lambda: self.user
        self.client = TestClient(server.app)
        cv = patch.object(server, 'load_cv_text', return_value='Fictional CV')
        cv.start()
        self.addCleanup(cv.stop)

    def tearDown(self):
        self.client.close()
        server.app.dependency_overrides.pop(server.get_current_user, None)
        server.app.state.background_queue = self.old_queue
        super().tearDown()

    def test_start_routes_refuse_a_user_without_their_own_cv(self):
        with patch.object(server, 'load_cv_text', return_value=''), \
                patch.object(server, '_run_scrape_bg') as scrape, patch.object(server, '_run_reprocess_bg') as reprocess:
            for path, body in (('/api/scrape', {'keywords': 'physics'}), ('/api/reprocess', None),
                               ('/api/generate/batch', {'job_ids': ['fictional']})):
                res = self.client.post(path, json=body)
                self.assertEqual(res.status_code, 400, path)
                self.assertEqual(res.json()['detail'], server.NO_CV_MESSAGE)
            scrape.assert_not_called()
            reprocess.assert_not_called()

    def test_three_start_routes_share_one_user_limit_and_reuse_without_cancelling(self):
        started = threading.Event()
        def scrape(task_id, *args):
            self.blocked(started)(task_id)
        with patch.object(server, '_run_scrape_bg', side_effect=scrape) as callback:
            scrape1 = self.client.post('/api/scrape', json={'keywords': 'physics'})
            self.assertEqual(scrape1.status_code, 200)
            self.assertTrue(started.wait(5))
            scrape2 = self.client.post('/api/scrape', json={'keywords': 'physics'})
            self.assertEqual(scrape1.json()['task_id'], scrape2.json()['task_id'])
            batch = self.client.post('/api/generate/batch', json={'job_ids': ['fictional']})
            self.assertEqual(batch.status_code, 200)
            self.assertEqual(batch.json()['status'], 'queued')
            reprocess = self.client.post('/api/reprocess')
            self.assertEqual(reprocess.status_code, 429)
            self.assertEqual(reprocess.headers['retry-after'], '5')
            self.assertFalse(self.row(scrape1.json())['cancelled'])
            self.assertEqual(callback.call_count, 1)
            active = self.client.get('/api/generate/batch/active').json()
            self.assertTrue(active['active'])
            self.assertEqual((active['status'], active['stage']), ('queued', 'queued'))
            self.client.post('/api/generate/batch/cancel')
            self.assertEqual(self.client.get('/api/generate/batch/status/' + batch.json()['task_id']).json()['status'], 'cancelled')
            self.release.set()
            self.queue.close()

    def test_rejected_or_queued_cancelled_all_scored_leaves_jobs_untouched(self):
        db.upsert_job({'id': 'scored', 'job_url': 'https://example.test/job', 'processed': 1,
                       'analysis_state': 'complete', 'match_score': 80}, user_id=self.user['id'])
        self.submit()
        second = self.submit({'second': True})
        with patch.object(db, 'load_all_jobs') as load:
            rejected = self.client.post('/api/reprocess?all_scored=true')
        load.assert_not_called()
        self.assertEqual(rejected.status_code, 429)
        self.assertEqual(db.get_job_by_id('scored', self.user['id'])['processed'], 1)
        self.queue.cancel(self.user['id'], task_id=second['task_id'])
        accepted = self.client.post('/api/reprocess?all_scored=true')
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(accepted.json()['status'], 'queued')
        self.client.post('/api/tasks/' + accepted.json()['task_id'] + '/cancel')
        job = db.get_job_by_id('scored', self.user['id'])
        self.assertEqual((job['processed'], job['analysis_state'], job['match_score']), (1, 'complete', 80))

    def test_status_and_cancel_are_owner_scoped_and_queued_reconnects(self):
        self.submit()
        queued = self.submit(kind='reprocess')
        active = self.client.get('/api/reprocess/active').json()
        self.assertEqual(active['task_id'], queued['task_id'])
        self.assertEqual(active['status'], 'queued')
        server.app.dependency_overrides[server.get_current_user] = lambda: self.other
        self.assertEqual(self.client.get('/api/reprocess/status/' + queued['task_id']).status_code, 404)
        self.assertEqual(self.client.post('/api/tasks/' + queued['task_id'] + '/cancel').status_code, 404)
        self.assertFalse(self.client.get('/api/reprocess/active').json()['active'])

    def test_batch_identity_uses_effective_settings_and_unique_jobs(self):
        with patch.object(server, 'load_generation_config', return_value=('configured', 'calm')), \
                patch.object(server, '_effective_ai_model', side_effect=lambda explicit, user: explicit or 'configured'), \
                patch.object(server, 'load_document_engine_config', return_value=('typst', 'template')), \
                patch.object(server, '_run_batch_generate_bg', side_effect=lambda tid, *args: self.blocked()(tid)):
            first = self.client.post('/api/generate/batch', json={'job_ids': ['b', 'a', 'a']}).json()
            equivalent = self.client.post('/api/generate/batch', json={
                'job_ids': ['a', 'b'], 'modelName': 'configured', 'tone': 'calm', 'engine': 'typst', 'force': None}).json()
            self.assertEqual(first['task_id'], equivalent['task_id'])
            self.assertEqual(first['total'], 2)
            with patch.object(server, 'load_generation_config', return_value=('configured', 'different')):
                changed = self.client.post('/api/generate/batch', json={'job_ids': ['a', 'b']}).json()
                self.assertNotEqual(first['task_id'], changed['task_id'])
                self.assertEqual(changed['status'], 'queued')
            self.release.set()
            self.queue.close()

    def test_lifespan_owns_recovery_and_refuses_second_worker(self):
        with self.assertRaises(BlockingIOError):
            with TestClient(server.app):
                pass
        self.queue.close()
        db.async_task_create('orphan', 'scrape', user_id=self.user['id'])
        with TestClient(server.app):
            self.assertEqual(db.async_task_get('orphan', self.user['id'])['status'], 'interrupted')
            self.assertIsNotNone(server.app.state.background_queue)
        self.assertIsNone(server.app.state.background_queue)
