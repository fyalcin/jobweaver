"""Finite backend operation admission, with one owner per data directory.

Only persistent scrape/reprocess/batch starts use this queue. Model and native
work in every process (including CLI, cron and synchronous routes) also takes
the shared slots in `capacity.py`.
"""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from contextlib import contextmanager
from contextvars import copy_context
from jobweaver.operation_budget import scope, check
from dataclasses import dataclass
import fcntl
import hashlib
import json
import logging
from pathlib import Path
import threading
import uuid

from jobweaver import db

logger = logging.getLogger(__name__)


@contextmanager
def bounded_results(fn, items, workers, *, cancelled=lambda: False):
    """Keep at most `workers` submitted children; drain running calls on cancel.

    Leaving the context also waits for children to exit. A parent operation must
    retain its queue slot while its provider/native calls can still be running.
    """
    iterator = iter(items)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        def results():
            pending = set()
            while True:
                while len(pending) < workers and not cancelled():
                    check()
                    try:
                        item = next(iterator)
                    except StopIteration:
                        break
                    pending.add(pool.submit(copy_context().run, fn, item))
                if not pending:
                    return
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    yield future.result()
        yield results()


@dataclass
class _Operation:
    task_id: str
    kind: str
    user_id: int
    key: str
    callback: object
    thread: object = None
    cancelled: bool = False


def _prune_usage_ledger():
    """Usage ledger retention (400 days). A busy ledger never blocks backend startup."""
    from jobweaver import model_usage
    import sqlite3
    try:
        model_usage.prune()
    except sqlite3.Error as exc:
        logger.warning('Usage ledger pruning skipped (%s).', type(exc).__name__)


class BackgroundQueue:
    def __init__(self, *, active=2, waiting=8, per_user=2):
        if active < 1 or waiting < 0 or per_user < 1:
            raise ValueError('Invalid background queue capacity')
        self.active_limit = active
        self.waiting_limit = waiting
        self.user_limit = per_user
        self._lock = threading.RLock()
        self._operations = {}  # Insertion order gives FIFO among eligible Users.
        self._owner = None
        self._closing = False

    def start(self):
        with self._lock:
            if self._owner is not None:
                raise RuntimeError('Background queue already started')
            # Never unlink the lock file: a replacement inode permits two owners.
            path = Path(db.DB_PATH).resolve().parent / '.jobweaver-backend.lock'
            owner = path.open('a')
            try:
                fcntl.flock(owner.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                db.async_task_recover_interrupted()
                db.async_task_prune_completed()
                _prune_usage_ledger()
            except BaseException:
                owner.close()
                raise
            self._owner = owner
            self._closing = False

    def submit(self, kind, user_id, payload, callback, *, total=None):
        """One critical section covers duplicate lookup, limits and DB creation.

        `callback(task_id)` runs only after admission and dispatch. In-memory
        reservations remain until its actual return, even if it writes a result.
        """
        key = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=False).encode()).hexdigest()
        with self._lock:
            if self._owner is None or self._closing:
                raise RuntimeError('Background queue is not accepting work')
            for operation in self._operations.values():
                if (operation.kind, operation.user_id, operation.key) == (kind, user_id, key):
                    return self._response(operation.task_id, user_id, True)
            running = [op for op in self._operations.values() if op.thread is not None]
            own = [op for op in self._operations.values() if op.user_id == user_id]
            can_start = len(running) < self.active_limit and not any(op.user_id == user_id for op in running)
            waiting = len(self._operations) - len(running)
            if len(own) >= self.user_limit or (not can_start and waiting >= self.waiting_limit):
                raise db.TaskCapacityError('Background queue is full for this account or server. Try again later.')
            db.async_task_prune_completed()
            task_id, reused = db.async_task_admit(str(uuid.uuid4()), kind, user_id, key, payload, total,
                max_total=self.active_limit + self.waiting_limit, max_user=self.user_limit)
            if not reused:
                self._operations[task_id] = _Operation(task_id, kind, user_id, key, callback)
                self._dispatch()
            return self._response(task_id, user_id, reused)

    @staticmethod
    def _response(task_id, user_id, reused):
        row = db.async_task_get(task_id, user_id)
        return {'success': True, 'task_id': task_id, 'reused': reused,
                'status': row['status'], 'stage': row['stage'], 'total': row['total']}

    def _dispatch(self):
        if self._closing:
            return
        running = [op for op in self._operations.values() if op.thread is not None]
        users = {op.user_id for op in running}
        for operation in list(self._operations.values()):
            if len(running) >= self.active_limit:
                break
            if operation.thread is not None or operation.user_id in users:
                continue
            db.async_task_update(operation.task_id, status='running')
            thread = threading.Thread(target=self._run, args=(operation,),
                                      name='background-operation', daemon=False)
            operation.thread = thread
            try:
                thread.start()
            except Exception:
                db.async_task_update(operation.task_id, status='failed',
                                     result={'success': False, 'message': 'Could not start background worker'})
                del self._operations[operation.task_id]
            else:
                running.append(operation)
                users.add(operation.user_id)

    def _run(self, operation):
        try:
            with self._lock:
                if operation.cancelled:
                    return
            with scope('collection', cancelled=lambda: operation.cancelled) as budget:
                budget.attribute(operation.user_id, 'background', task_id=operation.task_id)
                operation.callback(operation.task_id)
        except BaseException as exc:
            db.async_task_update(operation.task_id, status='failed',
                                 result={'success': False, 'message': f'Background task failed: {exc}'})
        finally:
            with self._lock:
                row = db.async_task_get(operation.task_id, operation.user_id)
                if operation.cancelled or (row and row['cancelled']):
                    db.async_task_update(operation.task_id, status='cancelled', cancelled=1,
                        result={'success': False, 'message': 'Cancelled after running calls finished. Saved work may already exist.'})
                elif row and row['status'] == 'running':
                    db.async_task_update(operation.task_id, status='completed')
                del self._operations[operation.task_id]
                self._dispatch()

    def cancel(self, user_id, *, kind=None, task_id=None):
        with self._lock:
            count = 0
            for operation in list(self._operations.values()):
                if operation.user_id != user_id or (kind and operation.kind != kind) or (task_id and operation.task_id != task_id):
                    continue
                operation.cancelled = True
                count += 1
                if operation.thread is None:
                    db.async_task_update(operation.task_id, status='cancelled', cancelled=1,
                        result={'success': False, 'message': 'Cancelled before execution'})
                    del self._operations[operation.task_id]
                else:
                    db.async_task_update(operation.task_id, cancelled=1, stage='cancelling')
            self._dispatch()
            return count

    def close(self):
        with self._lock:
            self._closing = True
            threads = [op.thread for op in self._operations.values() if op.thread is not None]
            for user_id in {op.user_id for op in self._operations.values()}:
                self.cancel(user_id)
        # Keep ownership until callbacks and their child pools truly exit.
        for thread in threads:
            thread.join()
        with self._lock:
            if self._owner:
                self._owner.close()
                self._owner = None
