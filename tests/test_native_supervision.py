"""Native tool supervision inside the full sandbox; fictional scripts and real processes only."""
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import capacity
import compiler_sandbox as cs
import db
from operation_budget import Budget, Limits, scope, OperationCancelled, OperationDeadline
from test_capacity import free, until

# Runs as the sandboxed tool. A setsid-detached grandchild writes a heartbeat.
HEARTBEAT = r'''
import os, sys, time
if os.fork() == 0:
    os.setsid()
    if os.fork() == 0:
        count = 0
        while True:
            count += 1
            with open('/work/beat.tmp', 'w') as handle:
                handle.write(str(count))
            os.replace('/work/beat.tmp', '/work/beat')
            time.sleep(.02)
    os._exit(0)
time.sleep(float(sys.argv[1]))
'''
SYSTEM_PYTHON = '/usr/bin/python3'
_which = shutil.which


def which(name, *args, **kwargs):
    return SYSTEM_PYTHON if name == 'python3' else _which(name, *args, **kwargs)


@unittest.skipUnless(Path(SYSTEM_PYTHON).is_file(), 'needs a system Python under /usr')
class NativeSupervisionTest(unittest.TestCase):
    def setUp(self):
        self.previous = db.DB_PATH
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name, 'data')
        self.work = Path(self.temp.name, 'work')
        self.root.mkdir()
        self.work.mkdir()
        db.set_db_path(str(self.root / 'test.db'))
        for patcher in (patch.object(cs, 'TOOLS', {'python3'}), patch.object(cs.shutil, 'which', which)):
            patcher.start()
            self.addCleanup(patcher.stop)

    def tearDown(self):
        db.set_db_path(self.previous)
        self.temp.cleanup()

    def run_python(self, code, *args, timeout=10):
        return cs.run_tool(['python3', '-c', code, *args], self.work, timeout=timeout)

    def beat(self):
        try:
            return (self.work / 'beat').read_text()
        except FileNotFoundError:
            return None

    def assert_stopped(self):
        before = self.beat()
        time.sleep(.3)
        self.assertEqual(self.beat(), before, 'detached descendant is still running')

    def test_bytes_result_interleaved_streams_and_released_slot(self):
        code = 'import sys\nfor i in range(200):\n    sys.stdout.write("o%d\\n" % i); sys.stderr.write("e%d\\n" % i)\nsys.exit(3)'
        result = self.run_python(code)
        self.assertIsInstance(result, subprocess.CompletedProcess)
        self.assertEqual(result.returncode, 3)
        self.assertEqual(result.stdout.count(b'\n'), 200)
        self.assertTrue(result.stderr.startswith(b'e0\n'))
        self.assertEqual(free('native', self.root), 2)

    def test_output_flood_on_each_stream_is_rejected(self):
        for stream, size in (('stdout', cs.STDOUT_LIMIT), ('stderr', cs.STDERR_LIMIT)):
            code = f'import sys, time\nsys.{stream}.buffer.write(b"x" * {size + 1}); sys.{stream}.flush(); time.sleep(30)'
            started = time.monotonic()
            with self.subTest(stream=stream), self.assertRaises(cs.ToolOutputLimit):
                self.run_python(code)
            self.assertLess(time.monotonic() - started, 5)
        self.assertEqual(free('native', self.root), 2)

    def test_no_output_stall_hits_tool_and_operation_deadlines(self):
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_python('import time; time.sleep(30)', timeout=.5)
        self.assertLess(time.monotonic() - started, 2)
        started = time.monotonic()
        with scope(budget=Budget(Limits(seconds=.5))), self.assertRaises(OperationDeadline):
            self.run_python('import time; time.sleep(30)', timeout=30)
        self.assertLess(time.monotonic() - started, 2)
        self.assertEqual(free('native', self.root), 2)

    def test_tmpfs_is_size_bounded(self):
        code = ('import sys\ntry:\n    with open("/tmp/fill", "wb") as f:\n        for _ in range(8): f.write(b"0" * 1048576)\n'
                'except OSError as e:\n    sys.exit(7)\n')
        self.assertEqual(self.run_python(code).returncode, 0)
        with patch.object(cs, 'TMPFS_BYTES', 2 * 1048576):
            self.assertEqual(self.run_python(code).returncode, 7)

    def test_early_tool_exit_still_removes_detached_descendants(self):
        result = self.run_python(HEARTBEAT, '0.3')
        self.assertEqual(result.returncode, 0)
        self.assertIsNotNone(self.beat())
        self.assert_stopped()
        self.assertEqual(free('native', self.root), 2)

    def test_cancel_kills_detached_grandchild_before_release(self):
        held = capacity.acquire('native', wait=0)
        cancel = threading.Event()
        during = []
        def watch():
            if until(lambda: self.beat() is not None, 10):
                during.append(free('native', self.root))
            cancel.set()
        threading.Thread(target=watch).start()
        try:
            with scope(budget=Budget(cancelled=cancel.is_set)), self.assertRaises(OperationCancelled), \
                    patch.object(cs, '_pidfd_kill', wraps=cs._pidfd_kill) as kill_init:
                self.run_python(HEARTBEAT, '60', timeout=30)
            # The namespace init was identified and killed, so the monitor reaped an empty namespace.
            kill_init.assert_called_once()
            # Read immediately: the slot is free only after the namespace is empty.
            after = self.beat()
            self.assertEqual(free('native', self.root), 1)
            time.sleep(.3)
            self.assertEqual(self.beat(), after, 'detached descendant outlived the released slot')
        finally:
            held.close()
        self.assertEqual(during, [0])

    def test_parent_sigkill_keeps_slot_until_independent_deadline(self):
        held = capacity.acquire('native', wait=0)
        parent = r'''
import shutil, sys
import db
db.set_db_path(sys.argv[1] + '/test.db')
import compiler_sandbox as cs
real = shutil.which
cs.shutil.which = lambda name, *a, **k: '/usr/bin/python3' if name == 'python3' else real(name, *a, **k)
cs.TOOLS = {'python3'}
cs._WALL_GRACE = .2
cs.run_tool(['python3', '-c', sys.argv[3], '60'], sys.argv[2], timeout=2)
'''
        try:
            process = subprocess.Popen([sys.executable, '-c', parent, str(self.root), str(self.work), HEARTBEAT],
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.assertTrue(until(lambda: self.beat() is not None, 15), 'sandbox did not start')
            finally:
                process.send_signal(signal.SIGKILL)
                process.wait()
            killed = time.monotonic()
            first = self.beat()
            time.sleep(.3)
            self.assertNotEqual(self.beat(), first, 'descendant should run until the wall deadline')
            self.assertEqual(free('native', self.root), 0)
            self.assertTrue(until(lambda: free('native', self.root) == 1, 6), 'slot never released')
            self.assert_stopped()
            self.assertLess(time.monotonic() - killed, 5)
        finally:
            held.close()

    def test_slot_and_info_descriptors_are_not_visible_inside_the_sandbox(self):
        code = r'''
import glob, os
for path in glob.glob('/proc/[0-9]*/fd/*'):
    try:
        target, info = os.readlink(path), os.stat(path)
    except OSError:
        continue
    print(path, target, info.st_dev, info.st_ino)
'''
        held = capacity.acquire('native', wait=0)  # Creates both slot files; the tool gets the other.
        held.close()
        locks = {(item.stat().st_dev, item.stat().st_ino) for item in (self.root / '.jobweaver-capacity').iterdir()}
        result = self.run_python(code)
        self.assertEqual(result.returncode, 0, result.stderr)
        lines = result.stdout.decode().splitlines()
        self.assertTrue(any(line.startswith('/proc/1/fd/') for line in lines), lines)
        for line in lines:
            path, target, device, inode = line.rsplit(' ', 3)
            self.assertNotIn('.jobweaver-capacity', target)
            self.assertNotIn((int(device), int(inode)), locks)
            if target.startswith('pipe:'):
                self.assertIn(path.rsplit('/', 1)[1], ('1', '2'), line)  # No --info-fd pipe either.

    def test_early_cancel_without_pid_report_kills_monitor_not_holder(self):
        held = capacity.acquire('native', wait=0)
        cancel = threading.Event()
        def watch():
            until(lambda: self.beat() is not None, 10)
            cancel.set()
        threading.Thread(target=watch).start()
        try:
            with patch.object(cs, '_namespace_init', return_value=None), \
                    patch.object(cs, '_pidfd_kill', wraps=cs._pidfd_kill) as kill, \
                    patch.object(cs.os, 'killpg', side_effect=AssertionError('holder must not be killed')), \
                    scope(budget=Budget(cancelled=cancel.is_set)), self.assertRaises(OperationCancelled):
                self.run_python(HEARTBEAT, '60', timeout=30)
            # Freeze the monitor, kill its namespace init, then the monitor; never the holder.
            self.assertEqual([call.args[1:] for call in kill.call_args_list],
                             [(signal.SIGSTOP,), (), ()])
            self.assertEqual(free('native', self.root), 1)
            self.assert_stopped()
        finally:
            held.close()

    def test_kill_failure_escalates_without_masking_the_cancel(self):
        cancel = threading.Event()
        threading.Timer(.5, cancel.set).start()
        with patch.object(cs, '_pidfd_kill', side_effect=PermissionError('fictional')), \
                scope(budget=Budget(cancelled=cancel.is_set)), self.assertRaises(OperationCancelled):
            self.run_python(HEARTBEAT, '60', timeout=30)
        self.assert_stopped()
        self.assertEqual(free('native', self.root), 2)


if __name__ == '__main__':
    unittest.main()
