"""Fixed cross-process slots for model POSTs and native document tools.

Every process that shares one data directory (backend, synchronous routes,
standalone CLI, scheduled runs) competes for the same lock files beside the
resolved database. The leaf calls `model_transport.post_json` and
`compiler_sandbox.run_tool` acquire a slot, so no entrypoint needs its own setup.

A slot is an exclusive `flock` on an independently opened file description.
Release happens only by closing descriptors: `LOCK_UN` would also unlock a copy
inherited by a helper or sandbox that is still running. Lock files are never
unlinked or truncated, because a replacement inode would admit a second holder.
"""
import fcntl
import os
from pathlib import Path
import stat
import time

from jobweaver.operation_budget import current, OperationBusy, OperationTerminated

# Common to all processes: a per-process setting could silently exceed the ceiling.
SLOTS = {'model': 4, 'native': 2}
WAIT_SECONDS = 20
_POLL = .05
_DIRECTORY = '.jobweaver-capacity'


class CapacityUnavailable(OperationTerminated):
    """The lock directory or a slot file is unusable. Fail closed; do not retry."""


class Lease:
    """Owns one slot descriptor. Pass `fileno()` to children that must keep the slot."""

    def __init__(self, pool, slot, descriptor):
        self.pool, self.slot, self._descriptor = pool, slot, descriptor

    def fileno(self):
        if self._descriptor < 0:
            raise ValueError('Capacity lease is closed')
        return self._descriptor

    def close(self):
        descriptor, self._descriptor = self._descriptor, -1
        if descriptor >= 0:
            os.close(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def directory(data_dir=None):
    """Resolve lazily so `db.set_db_path`, JOBWEAVER_DATA_DIR and symlinks apply."""
    if data_dir is None:
        from jobweaver import db
        base = Path(db.DB_PATH).resolve().parent
    else:
        base = Path(data_dir).resolve()
    return base / _DIRECTORY


def _unavailable(exc):
    return CapacityUnavailable(f'Shared work capacity is unavailable ({type(exc).__name__}: '
                               f'{getattr(exc, "strerror", None) or exc}).')


def _repair(handle, name):
    """Restore 0600 once on our own regular slot file; anything else fails closed."""
    try:
        path = os.open(name, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=handle)
    except OSError as exc:
        raise _unavailable(exc) from exc
    try:
        info = os.fstat(path)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise CapacityUnavailable('Shared work capacity is unavailable (slot file is not ours).')
        os.chmod(f'/proc/self/fd/{path}', 0o600)  # The inode itself; never a symlink target.
    except OSError as exc:
        raise _unavailable(exc) from exc
    finally:
        os.close(path)


def _try(handle, pool, slot):
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
    name = f'{pool}-{slot}.lock'
    try:
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=handle)
        except PermissionError:
            _repair(handle, name)
            descriptor = os.open(name, flags, 0o600, dir_fd=handle)
    except OSError as exc:
        raise _unavailable(exc) from exc
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid():
            raise CapacityUnavailable('Shared work capacity is unavailable (slot is not our regular file).')
        if stat.S_IMODE(info.st_mode) != 0o600:
            os.fchmod(descriptor, 0o600)
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(descriptor)
        return None
    except OSError as exc:
        os.close(descriptor)
        raise _unavailable(exc) from exc
    except BaseException:
        os.close(descriptor)
        raise
    return Lease(pool, slot, descriptor)


def acquire(pool, *, data_dir=None, wait=None):
    """Return a Lease, or raise OperationBusy after a short cancellable wait.

    The wait never extends past the current operation deadline. Busy is terminal:
    nothing was dispatched, and callers must not retry automatically.
    """
    count = SLOTS[pool]
    budget = current()
    end = time.monotonic() + (WAIT_SECONDS if wait is None else wait)
    if budget:
        budget.check()
        end = min(end, budget.deadline)
    folder = directory(data_dir)
    try:
        folder.mkdir(mode=0o700, exist_ok=True)
        handle = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError as exc:
        raise _unavailable(exc) from exc
    try:
        while True:
            for slot in range(count):
                lease = _try(handle, pool, slot)
                if lease:
                    return lease
            remaining = end - time.monotonic()
            if remaining <= 0:
                if budget:
                    budget.check()  # A wait cut short by deadline/cancel reports that, not busy.
                raise OperationBusy(f'The server is busy: all {count} shared {pool} slots are in use. '
                                    'This step was not sent or started. Try again shortly.')
            time.sleep(min(_POLL, remaining))
            if budget:
                budget.check()
    finally:
        os.close(handle)
