"""Shared cross-process model/native slots; fictional fixtures and real processes only."""
import asyncio
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from jobweaver import capacity
from jobweaver import db
from jobweaver import generators
from jobweaver import model_transport as mt
from jobweaver.operation_budget import (Budget, Limits, scope, OperationBusy, OperationCancelled, OperationDeadline,
                              OperationTerminated)


def free(pool, root):
    """Count currently admissible slots without waiting."""
    leases = []
    try:
        while True:
            leases.append(capacity.acquire(pool, data_dir=root, wait=0))
    except OperationBusy:
        return len(leases)
    finally:
        for lease in leases:
            lease.close()


def alive(pid):
    try:
        state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
    except OSError:
        return False
    return state != 'Z'


def until(condition, seconds, interval=.02):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(interval)
    return condition()


class CapacityTest(unittest.TestCase):
    def setUp(self):
        self.previous = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name, 'data')
        self.root.mkdir()
        db.set_db_path(str(self.root / 'test.db'))

    def tearDown(self):
        db.set_db_path(self.previous)
        self.temp.cleanup()

    def test_exact_slots_then_bounded_busy_wait(self):
        for pool, count in capacity.SLOTS.items():
            with self.subTest(pool=pool):
                leases = [capacity.acquire(pool, wait=0) for _ in range(count)]
                self.assertEqual(sorted(lease.slot for lease in leases), list(range(count)))
                started = time.monotonic()
                with self.assertRaises(OperationBusy):
                    capacity.acquire(pool, wait=.3)
                self.assertGreaterEqual(time.monotonic() - started, .28)
                self.assertLess(time.monotonic() - started, 1.5)
                leases.pop().close()
                capacity.acquire(pool, wait=0).close()
                for lease in leases:
                    lease.close()
                self.assertEqual(free(pool, self.root), count)
        self.assertEqual(capacity.SLOTS, {'model': 4, 'native': 2})

    def test_waiter_is_admitted_when_a_slot_frees(self):
        leases = [capacity.acquire('native') for _ in range(2)]
        threading.Timer(.2, leases[0].close).start()
        started = time.monotonic()
        with capacity.acquire('native', wait=3) as lease:
            self.assertEqual(lease.slot, 0)
        self.assertLess(time.monotonic() - started, 2)
        leases[1].close()

    def test_independent_opens_and_threads_in_one_process_contend(self):
        barrier = threading.Barrier(8)
        won, lost = [], []
        def contend():
            barrier.wait()
            try:
                won.append(capacity.acquire('model', wait=0))
            except OperationBusy:
                lost.append(1)
        threads = [threading.Thread(target=contend) for _ in range(8)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        self.assertEqual((len(won), len(lost)), (4, 4))
        for lease in won: lease.close()

    def test_two_real_processes_contend(self):
        code = ('import sys; from jobweaver import capacity\n'
                'held = [capacity.acquire("model", data_dir=sys.argv[1], wait=0) for _ in range(3)]\n'
                'print("ready", flush=True)\nsys.stdin.read()\n')
        child = subprocess.Popen([sys.executable, '-c', code, str(self.root)], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(), 'ready')
            self.assertEqual(free('model', self.root), 1)
            with capacity.acquire('model', wait=0), self.assertRaises(OperationBusy):
                capacity.acquire('model', wait=.1)
        finally:
            child.kill()
            child.wait()
            child.stdin.close()
            child.stdout.close()
        self.assertEqual(free('model', self.root), 4)

    def test_symlink_alias_contends_and_other_roots_do_not(self):
        alias = Path(self.temp.name, 'alias')
        alias.symlink_to(self.root, target_is_directory=True)
        other = Path(self.temp.name, 'other')
        other.mkdir()
        leases = [capacity.acquire('native', data_dir=self.root, wait=0) for _ in range(2)]
        self.assertEqual(free('native', alias), 0)
        db.set_db_path(str(alias / 'test.db'))
        with self.assertRaises(OperationBusy):
            capacity.acquire('native', wait=0)
        self.assertEqual(free('native', other), 2)
        for lease in leases: lease.close()

    def test_default_root_follows_set_db_path(self):
        moved = Path(self.temp.name, 'moved')
        moved.mkdir()
        db.set_db_path(str(moved / 'elsewhere.db'))
        with capacity.acquire('model') as lease:
            path = moved / '.jobweaver-capacity' / f'model-{lease.slot}.lock'
            self.assertTrue(path.is_file())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(free('model', moved), 3)
            self.assertEqual(free('model', self.root), 4)

    def test_wait_obeys_operation_cancel_and_deadline(self):
        leases = [capacity.acquire('model') for _ in range(4)]
        try:
            started = time.monotonic()
            with scope(budget=Budget(Limits(seconds=.2))), self.assertRaises(OperationDeadline):
                capacity.acquire('model', wait=20)
            self.assertLess(time.monotonic() - started, .6)
            with scope(budget=Budget()), self.assertRaises(OperationBusy) as busy:
                capacity.acquire('model', wait=.1)
            self.assertIn('This step was not sent or started', str(busy.exception))
            self.assertLess(time.monotonic() - started, .6)
            event = threading.Event()
            threading.Timer(.1, event.set).start()
            started = time.monotonic()
            with scope(budget=Budget(cancelled=event.is_set)), self.assertRaises(OperationCancelled):
                capacity.acquire('model', wait=20)
            self.assertLess(time.monotonic() - started, .6)
        finally:
            for lease in leases: lease.close()

    def test_invalid_lock_paths_fail_closed(self):
        folder = self.root / '.jobweaver-capacity'
        folder.mkdir()
        (folder / 'model-0.lock').symlink_to(self.root / 'target')
        with self.assertRaises(capacity.CapacityUnavailable):
            capacity.acquire('model', wait=0)
        self.assertFalse((self.root / 'target').exists())
        (folder / 'native-0.lock').mkdir()
        with self.assertRaises(capacity.CapacityUnavailable):
            capacity.acquire('native', wait=0)
        linked = Path(self.temp.name, 'linked')
        linked.mkdir()
        (linked / '.jobweaver-capacity').symlink_to(folder, target_is_directory=True)
        with self.assertRaises(capacity.CapacityUnavailable):
            capacity.acquire('model', data_dir=linked, wait=0)
        with self.assertRaises(capacity.CapacityUnavailable):
            capacity.acquire('model', data_dir=Path(self.temp.name, 'missing'), wait=0)
        self.assertTrue(issubclass(capacity.CapacityUnavailable, OperationTerminated))

    def test_own_slot_file_permissions_are_repaired(self):
        folder = self.root / '.jobweaver-capacity'
        for mode in (0o000, 0o640):
            with self.subTest(mode=oct(mode)):
                capacity.acquire('native', wait=0).close()
                (folder / 'native-0.lock').chmod(mode)
                with capacity.acquire('native', wait=0) as lease:
                    self.assertEqual(lease.slot, 0)
                self.assertEqual((folder / 'native-0.lock').stat().st_mode & 0o777, 0o600)

    def test_busy_preview_is_skipped_but_cancel_stays_terminal(self):
        pdf = Path(self.temp.name, 'fictional.pdf')
        pdf.write_bytes(b'%PDF-1.4 fictional')
        leases = [capacity.acquire('native') for _ in range(2)]
        try:
            shared = Budget()
            with patch.object(capacity, 'WAIT_SECONDS', .1), scope(budget=shared):
                self.assertEqual(generators.convert_pdf_to_images(str(pdf), self.temp.name, 'preview'), [])
                shared.check()  # Busy did not end the operation.
            cancel = threading.Event()
            threading.Timer(.1, cancel.set).start()
            with patch.object(capacity, 'WAIT_SECONDS', 5), self.assertRaises(OperationCancelled), \
                    scope(budget=Budget(cancelled=cancel.is_set)):
                generators.convert_pdf_to_images(str(pdf), self.temp.name, 'preview')
        finally:
            for lease in leases: lease.close()

    def test_real_helper_entry_arms_deadline_before_importing_requests(self):
        started = time.monotonic()
        helper = subprocess.Popen([sys.executable, '-m', 'jobweaver.model_transport', '--worker'], stdin=subprocess.PIPE,
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        helper.stdin.write(b'0.3\n')
        helper.stdin.flush()  # The envelope never arrives; only the helper's own alarm ends it.
        try:
            self.assertEqual(helper.wait(5), -signal.SIGALRM)
        finally:
            helper.kill()
            helper.communicate()
        self.assertLess(time.monotonic() - started, 4)
        probe = r'''
import importlib.abc, runpy, signal, sys
class Probe(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name == 'requests':
            sys.stderr.write('itimer=%r mask=%r\n' % (signal.getitimer(signal.ITIMER_REAL)[0],
                                                       signal.SIGALRM in signal.pthread_sigmask(signal.SIG_BLOCK, [])))
        return None
assert 'requests' not in sys.modules
sys.meta_path.insert(0, Probe())
signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
sys.argv = ['model_transport', '--worker']
runpy.run_module('jobweaver.model_transport', run_name='__main__')
'''
        result = subprocess.run([sys.executable, '-c', probe], input=b'5\n{}', capture_output=True, timeout=20)
        report = [line for line in result.stderr.decode().splitlines() if line.startswith('itimer=')]
        self.assertTrue(report, result.stderr)
        itimer, blocked = report[0].split()
        self.assertGreater(float(itimer.split('=')[1]), 0, 'deadline was not armed before requests import')
        self.assertEqual(blocked, 'mask=False', 'SIGALRM stayed blocked')

    def test_close_only_release_keeps_child_held_lease(self):
        lease = capacity.acquire('model')
        child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], pass_fds=(lease.fileno(),))
        try:
            lease.close()
            self.assertEqual(free('model', self.root), 3)
        finally:
            child.kill()
            child.wait()
        self.assertEqual(free('model', self.root), 4)

    def test_busy_never_dispatches_a_model_post_and_is_not_retried(self):
        leases = [capacity.acquire('model') for _ in range(4)]
        shared = Budget().attribute(1, 'cli')  # Busy precedes every ledger access.
        try:
            with patch.object(capacity, 'WAIT_SECONDS', .1), patch.object(mt.subprocess, 'Popen') as launch, \
                    patch.object(capacity, 'acquire', wraps=capacity.acquire) as admit, \
                    patch.dict(os.environ, OPENROUTER_API_KEY='fictional'), scope(budget=shared):
                with self.assertRaises(OperationBusy):
                    generators.run_ai_prompt('fictional prompt', model_name='fictional/model')
            launch.assert_not_called()
            self.assertEqual(admit.call_count, 1)
            self.assertEqual(shared.attempts, 0)
        finally:
            for lease in leases: lease.close()

    def test_busy_maps_to_service_unavailable_with_retry_after(self):
        from jobweaver import server
        response = asyncio.run(server.operation_terminal_response(None, OperationBusy('busy')))
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.headers['Retry-After'], '5')

    def test_model_helper_keeps_lease_after_parent_death_and_self_terminates(self):
        marker = Path(self.temp.name, 'helper.pid')
        parent = r'''
import subprocess, sys
from jobweaver import db
db.set_db_path(sys.argv[1] + '/test.db')
db.init_db()
owner = db.create_user('helper-owner', password_hash='fictional')['id']
from jobweaver import model_transport as mt
from jobweaver.operation_budget import Budget, Limits, scope
mt._HELPER_GRACE = .5
code = """
import os, time, requests
from jobweaver import model_transport as mt
class Session:
    trust_env = True
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def post(self, url, **kwargs):
        open(MARKER, 'w').write(str(os.getpid()))
        time.sleep(60)
requests.Session = Session
mt._worker()
""".replace('MARKER', repr(sys.argv[2]))
real = subprocess.Popen
mt.subprocess.Popen = lambda command, **kwargs: real([sys.executable, '-c', code], **kwargs)
with scope(budget=Budget(Limits(seconds=1.5)).attribute(owner, 'cli')):
    mt.post_json('http://localhost', headers={}, json={'messages': [], 'max_tokens': 1})
'''
        process = subprocess.Popen([sys.executable, '-c', parent, str(self.root), str(marker)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            self.assertTrue(until(lambda: marker.exists() and marker.read_text(), 15), 'helper did not start')
            helper = int(marker.read_text())
        finally:
            process.send_signal(signal.SIGKILL)
            process.wait()
        killed = time.monotonic()
        self.assertTrue(alive(helper))
        self.assertEqual(free('model', self.root), 3)
        time.sleep(.4)
        self.assertTrue(alive(helper), 'helper exited with its parent, before its own deadline')
        self.assertEqual(free('model', self.root), 3)
        self.assertTrue(until(lambda: free('model', self.root) == 4, 5), 'helper lease never released')
        self.assertFalse(alive(helper))
        self.assertLess(time.monotonic() - killed, 4)


if __name__ == '__main__':
    unittest.main()
