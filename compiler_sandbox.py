"""Run document tools with explicit inputs, no personal filesystem and no network.

Linux native builds require Bubblewrap and prlimit. There is deliberately no
unsandboxed fallback. Browser Typst export and prepared demo reads do not use this.

Process tree: slot holder -> prlimit/bwrap monitor -> namespace init -> tool.
Each run holds one shared native slot (`capacity.py`). Only this process and the
small holder keep that descriptor; Bubblewrap passes inherited descriptors to the
tool, so the holder marks it close-on-exec before starting the monitor. The holder
waits for the monitor, and the monitor waits for the namespace init, which the
kernel reaps only after every sandbox process (including detached sessions) is
gone. The holder's wall deadline survives the death of this process.
"""
from pathlib import Path
import json
import os
import platform
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time
from operation_budget import current, check

TOOLS = {'pdflatex', 'typst', 'latexdiff', 'pdfinfo', 'pdftoppm', 'pdftotext'}
# Realistic fictional CVs give ~10 KiB latexdiff output and small diagnostics.
STDOUT_LIMIT = 4 * 1024 * 1024
STDERR_LIMIT = 256 * 1024
TMPFS_BYTES = 256 * 1024 * 1024
_WALL_GRACE = 2.0  # The parent normally stops the tool first.
_INTERVAL = .05
_REAP_SECONDS = 5.0
_DRAIN_SECONDS = 2.0
_INFO_LIMIT = 4096
_INFO_WAIT = 1.0  # An early cancel waits this long for Bubblewrap's PID report.

# Holds the slot outside the sandbox: never passes it on, waits for the monitor,
# and kills it at a wall deadline that does not depend on the parent.
_HOLDER = r'''
import os, subprocess, sys
lease, info, wall = int(sys.argv[1]), int(sys.argv[2]), float(sys.argv[3])
os.set_inheritable(lease, False)
monitor = subprocess.Popen(sys.argv[4:], pass_fds=(info,), stdin=subprocess.DEVNULL)
os.close(info)
try:
    code = monitor.wait(wall)
except subprocess.TimeoutExpired:
    # Kill the namespace init first: the monitor then exits only after the namespace is empty.
    try:
        with open(f'/proc/{monitor.pid}/task/{monitor.pid}/children') as children:
            for pid in children.read().split():
                os.kill(int(pid), 9)
    except OSError:
        pass
    try:
        code = monitor.wait(5)
    except subprocess.TimeoutExpired:
        monitor.kill()
        code = monitor.wait()
sys.exit(128 - code if code < 0 else code)
'''


class ToolOutputLimit(subprocess.SubprocessError):
    """The tool wrote more than its output allowance; it was stopped, not truncated."""


def run_tool(command, cwd, *, assets=None, timeout=45):
    check()
    budget = current()
    name = command[0]
    if name not in TOOLS:
        raise ValueError('Unsupported document tool')
    bubblewrap, limits, binary = (shutil.which(tool) for tool in ('bwrap', 'prlimit', name))
    if not bubblewrap or not limits:
        raise OSError('Native document tools require Bubblewrap and prlimit for isolation. No unsafe fallback is enabled.')
    if not binary:
        raise OSError(f'Document tool is not installed: {name}')
    work = Path(cwd).resolve()
    arguments = ['--die-with-parent', '--new-session', '--unshare-all', '--cap-drop', 'ALL', '--clearenv']
    # System binaries/libraries and public TeX/font resources only. Never mount
    # the checkout, data directory, environment files or the operator's home.
    roots = ['/usr', '/bin', '/lib', '/lib64', '/etc/texmf', '/etc/fonts',
             '/var/lib/texmf', '/var/cache/fontconfig']
    brew = Path('/home/linuxbrew/.linuxbrew')
    if Path(binary).resolve().is_relative_to(brew):
        roots.append(str(brew))
    import user_assets
    protected = [Path(path).resolve() for path in
                 (user_assets.BASE_DIR, user_assets.DATA_DIR, user_assets.PROFILES_DIR)]
    for root in roots:
        if Path(root).exists():
            if any(path.is_relative_to(Path(root).resolve()) for path in protected):
                raise OSError('Keep the checkout and personal data outside the public system/compiler resource directories')
            arguments += ['--ro-bind', root, root]
    arguments += ['--proc', '/proc', '--dev', '/dev', '--size', str(TMPFS_BYTES), '--tmpfs', '/tmp',
                  '--bind', str(work), '/work', '--chdir', '/work',
                  '--setenv', 'PATH', '/usr/bin:/bin', '--setenv', 'LANG', 'C.UTF-8',
                  '--setenv', 'TEXMFVAR', '/tmp/texmf-var', '--setenv', 'TEXMFCONFIG', '/tmp/texmf-config',
                  '--setenv', 'TEXMFCACHE', '/tmp/texmf-cache']
    if assets:
        assets = Path(assets).resolve()
        arguments += ['--ro-bind', str(assets), '/assets']

    def mapped(value):
        value = str(value)
        for original, target in ((str(work), '/work'), (str(assets), '/assets') if assets else ('', '')):
            if original and (value == original or value.startswith(original + os.sep)):
                return target + value[len(original):]
        return value

    # TeX selects its format from argv[0]; retain the pdflatex symlink name.
    arguments += ['--', binary, *(mapped(arg) for arg in command[1:])]
    import capacity
    with capacity.acquire('native') as lease:
        # The effective deadline starts after admission and never passes the operation's.
        seconds = min(timeout, budget.remaining()) if budget else timeout
        chain = [limits, '--as=1073741824', '--cpu=30', '--fsize=33554432', '--nofile=256', '--', bubblewrap]
        return _supervise(chain, arguments, work, lease, seconds, timeout, command)


def _supervise(chain, arguments, work, lease, seconds, timeout, command):
    """Bounded concurrent drains; stop and reap the whole sandbox before returning."""
    deadline = time.monotonic() + seconds
    info_read, info_write = os.pipe()
    try:
        process = subprocess.Popen(
            [sys.executable, '-I', '-c', _HOLDER, str(lease.fileno()), str(info_write),
             f'{seconds + _WALL_GRACE:.3f}', *chain, '--info-fd', str(info_write), *arguments],
            cwd=work, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env={'PATH': '/usr/bin:/bin'}, pass_fds=(lease.fileno(), info_write), start_new_session=True)
    except BaseException:
        os.close(info_read)
        raise
    finally:
        os.close(info_write)
    output, errors, info = bytearray(), bytearray(), bytearray()
    streams = {process.stdout.fileno(): (output, STDOUT_LIMIT, 'stdout'),
               process.stderr.fileno(): (errors, STDERR_LIMIT, 'stderr'), info_read: (info, _INFO_LIMIT, 'info')}
    state = {'init': None}
    selector = selectors.DefaultSelector()

    def receive(descriptor):
        chunk = os.read(descriptor, 65536)
        if not chunk:
            selector.unregister(descriptor)
            return
        target, limit, label = streams[descriptor]
        if len(target) + len(chunk) > limit:
            raise ToolOutputLimit(f'Document tool {label} exceeds the {limit // 1024} KiB limit; '
                                  'the tool was stopped.')
        target.extend(chunk)
        if descriptor == info_read and state['init'] is None:
            state['init'] = _namespace_init(info)

    def await_init():
        """Early stop: give Bubblewrap a bounded moment to report the namespace PID."""
        end = time.monotonic() + _INFO_WAIT
        while state['init'] is None and info_read in selector.get_map() and process.poll() is None:
            remaining = end - time.monotonic()
            if remaining <= 0:
                return
            if any(key.fd == info_read for key, _ in selector.select(min(_INTERVAL, remaining))):
                try:
                    receive(info_read)
                except (OSError, ValueError, KeyError):
                    return

    try:
        for descriptor in streams:
            os.set_blocking(descriptor, False)
            selector.register(descriptor, selectors.EVENT_READ)
        while selector.get_map() or process.poll() is None:
            check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(command, timeout, bytes(output), bytes(errors))
            if not selector.get_map():
                time.sleep(min(_INTERVAL, remaining))
                continue
            for key, _ in selector.select(min(_INTERVAL, remaining)):
                receive(key.fd)
        check()
        if time.monotonic() >= deadline:
            raise subprocess.TimeoutExpired(command, timeout, bytes(output), bytes(errors))
        return subprocess.CompletedProcess(command, process.returncode, bytes(output), bytes(errors))
    finally:
        try:
            if process.poll() is None and state['init'] is None:
                await_init()
            _stop(process, state['init'])
            _drain(selector)
        finally:
            selector.close()
            for descriptor in (process.stdout, process.stderr):
                descriptor.close()
            os.close(info_read)
            if state['init'] is not None and state['init'] >= 0:
                os.close(state['init'])


def _namespace_init(info):
    """Return a pidfd for the sandbox PID 1 once Bubblewrap reports it."""
    if b'}' not in info:
        return None
    report = json.loads(info[:info.index(b'}') + 1])
    pid, namespace = report['child-pid'], report['pid-namespace']
    try:
        handle = _pidfd_open(pid)
    except ProcessLookupError:
        return -1
    if handle is None:
        return -1
    # Guard against PID reuse before the pidfd: it must be PID 1 of the reported namespace.
    try:
        same = os.readlink(f'/proc/{pid}/ns/pid') == f'pid:[{namespace}]'
        nspid = re.search(r'^NSpid:\s+(.+)$', Path(f'/proc/{pid}/status').read_text(), re.M)
        same = same and nspid is not None and nspid.group(1).split()[-1] == '1'
    except OSError:
        same = False
    if not same:
        os.close(handle)
        return -1
    return handle


def _parent(pid):
    return int(Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[1])


def _child(parent):
    """(pidfd, pid) for a child of `parent`, verified after opening; None if absent/unsupported."""
    try:
        for child in map(int, Path(f'/proc/{parent}/task/{parent}/children').read_text().split()):
            handle = _pidfd_open(child)
            if handle is None:
                return None
            if _parent(child) == parent:
                return handle, child
            os.close(handle)
    except (OSError, ValueError):
        pass
    return None


def _stop_without_report(holder):
    """No PID report: freeze the monitor so it cannot clone, kill its child, then the monitor.

    The holder keeps the slot until it has reaped the monitor."""
    monitor = _child(holder)
    if monitor is None:
        return False
    handle, pid = monitor
    try:
        _pidfd_kill(handle, signal.SIGSTOP)
        end = time.monotonic() + _INFO_WAIT
        while time.monotonic() < end:
            try:
                state = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[0]
            except OSError:
                break
            if state in 'TtZX':
                break
            time.sleep(.005)
        init = _child(pid)
        if init is not None:
            try:
                _pidfd_kill(init[0])
            finally:
                os.close(init[0])
        _pidfd_kill(handle)
        return True
    except OSError:
        return False
    finally:
        os.close(handle)


# Some standalone Python builds omit the wrappers; these numbers are the generic table's.
_PIDFD_SYSCALLS = {'open': 434, 'send_signal': 424}
_GENERIC_SYSCALL_MACHINES = {'x86_64', 'aarch64', 'arm64', 'riscv64', 'ppc64le', 's390x'}


def _syscall(name, *arguments):
    import ctypes
    libc = ctypes.CDLL(None, use_errno=True)
    result = libc.syscall(_PIDFD_SYSCALLS[name], *arguments)
    if result < 0:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result


def _pidfd_open(pid):
    if hasattr(os, 'pidfd_open'):
        return os.pidfd_open(pid)
    if platform.machine() not in _GENERIC_SYSCALL_MACHINES:
        return None
    import ctypes
    return _syscall('open', ctypes.c_int(pid), ctypes.c_uint(0))


def _pidfd_kill(handle, number=signal.SIGKILL):
    if hasattr(signal, 'pidfd_send_signal'):
        return signal.pidfd_send_signal(handle, number)
    import ctypes
    _syscall('send_signal', ctypes.c_int(handle), ctypes.c_int(number), None, ctypes.c_uint(0))


def _stop(process, init):
    """Kill PID 1 so the holder exits only after the namespace is empty; escalate last."""
    if process.poll() is None:
        sent = False
        if init is not None and init >= 0:
            try:
                _pidfd_kill(init)
                sent = True
            except OSError:
                pass
        else:
            sent = _stop_without_report(process.pid)
        if sent:
            try:
                process.wait(_REAP_SECONDS)
            except subprocess.TimeoutExpired:
                pass
    if process.poll() is None:
        # Final escalation; Bubblewrap's parent-death chain then removes the namespace.
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            pass
        process.kill()
    process.wait()


def _drain(selector):
    end = time.monotonic() + _DRAIN_SECONDS
    while selector.get_map() and (remaining := end - time.monotonic()) > 0:
        for key, _ in selector.select(min(_INTERVAL, remaining)):
            try:
                chunk = os.read(key.fd, 65536)
            except BlockingIOError:
                continue
            if not chunk:
                selector.unregister(key.fd)
