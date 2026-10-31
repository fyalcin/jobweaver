"""Finite, in-process allowances shared by all stages of one operation.

Reservations count attempted POSTs, including refusals and unknown outcomes. They
are never refunded. Bytes are UTF-8 bytes, not tokens or monetary accounting.
"""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from functools import wraps
import inspect
import threading
import math
import time
import uuid


class OperationTerminated(RuntimeError):
    """Terminal: callers must not retry or start another stage/job."""


class OperationCancelled(OperationTerminated):
    pass


class OperationDeadline(OperationTerminated):
    pass


class OperationExhausted(OperationTerminated):
    pass


class OperationBusy(OperationTerminated):
    """Shared model/native capacity stayed full; nothing was dispatched."""


class QuotaExceeded(OperationExhausted):
    """The owning User's daily model request quota is used up; nothing was sent.

    `retry_after` is the number of seconds until the quota day resets.
    """

    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class UsageLedgerUnavailable(OperationBusy):
    """The usage ledger could not record the attempt in time; nothing was sent."""


class AttributionError(OperationTerminated):
    """The operation has no owning User, or a second owner was requested."""


ORIGINS = ('web', 'background', 'scheduled', 'cli')


@dataclass(frozen=True)
class Limits:
    seconds: float = 600
    attempts: int = 16
    prompt_bytes: int = 64 * 1024 * 1024
    payload_bytes: int = 80 * 1024 * 1024
    output_tokens: int = 128000
    response_bytes: int = 16 * 1024 * 1024
    prompt_per_call: int = 8 * 1024 * 1024
    payload_per_call: int = 10 * 1024 * 1024
    response_per_call: int = 2 * 1024 * 1024
    output_per_call: int = 8000


DEFAULTS = {
    'interactive': Limits(),
    'documents': Limits(),
    'collection': Limits(seconds=1800, attempts=120, prompt_bytes=512 * 1024 * 1024,
                         payload_bytes=640 * 1024 * 1024, output_tokens=960000,
                         response_bytes=64 * 1024 * 1024),
}
_CURRENT = ContextVar('jobweaver_operation_budget', default=None)


class Budget:
    def __init__(self, limits=None, *, cancelled=lambda: False):
        self.limits = limits or Limits()
        if any(not math.isfinite(value) or value <= 0 for value in vars(self.limits).values()):
            raise ValueError('Operation limits must be positive')
        self.deadline = time.monotonic() + self.limits.seconds
        self._cancelled = [cancelled]
        self._lock = threading.RLock()
        self._terminal = None
        self.attempts = self.prompt_bytes = self.payload_bytes = self.output_tokens = self.response_bytes = 0
        # Attribution for the durable usage ledger and per-User quotas (`model_usage.py`).
        self.operation_id = uuid.uuid4().hex
        self.purpose = 'interactive'
        self.owner = self.origin = self.task_id = None

    def attribute(self, owner, origin, task_id=None):
        """Set the owning User once. A different User later is a terminal error."""
        if isinstance(owner, bool) or not isinstance(owner, int) or owner <= 0:
            raise ValueError('Operation owner must be a positive User id')
        if origin not in ORIGINS:
            raise ValueError('Unknown operation origin')
        if task_id is not None and not isinstance(task_id, str):
            raise ValueError('Operation task id must be text')
        with self._lock:
            if self.owner is None:
                self.owner, self.origin = owner, origin
            elif self.owner != owner:
                self._stop(AttributionError('Operation already belongs to another User.'))
            if self.task_id is None:
                self.task_id = task_id
            return self

    def add_cancel_check(self, callback):
        with self._lock:
            self._cancelled.append(callback)

    def terminate(self, error):
        """Latch the first terminal failure so sibling stages also stop."""
        with self._lock:
            if self._terminal is None:
                self._terminal = error
            return self._terminal

    def _stop(self, error):
        raise self.terminate(error)

    def remove_cancel_check(self, callback):
        with self._lock:
            self._cancelled.remove(callback)

    def check(self):
        with self._lock:
            if self._terminal:
                raise self._terminal
            if any(callback() for callback in self._cancelled):
                self._stop(OperationCancelled('Operation cancelled. Saved work may already exist.'))
            if time.monotonic() >= self.deadline:
                self._stop(OperationDeadline('Operation deadline exceeded. Provider outcome may be unknown.'))

    def remaining(self):
        self.check()
        return max(0.0, self.deadline - time.monotonic())

    def reserve(self, prompt_bytes, payload_bytes, output_tokens):
        with self._lock:
            self.check()
            values = dict(attempts=1, prompt_bytes=prompt_bytes, payload_bytes=payload_bytes, output_tokens=output_tokens)
            for name, value in values.items():
                per_call = getattr(self.limits, {'prompt_bytes': 'prompt_per_call', 'payload_bytes': 'payload_per_call',
                                              'output_tokens': 'output_per_call'}.get(name, 'attempts'))
                if value > per_call or getattr(self, name) + value > getattr(self.limits, name):
                    self._stop(OperationExhausted('Operation model allowance exhausted (' + name + ').'))
            for name, value in values.items():
                setattr(self, name, getattr(self, name) + value)

    def consume_response(self, size):
        with self._lock:
            self.check()
            if size > self.limits.response_per_call or self.response_bytes + size > self.limits.response_bytes:
                self._stop(OperationExhausted('Operation model response allowance exhausted.'))
            self.response_bytes += size

    def wait(self, seconds):
        end = time.monotonic() + seconds
        while True:
            remaining = self.remaining()
            delay = min(.05, remaining, end - time.monotonic())
            if delay <= 0:
                self.check()
                return
            time.sleep(delay)


def current():
    return _CURRENT.get()


def check():
    budget = current()
    if budget:
        budget.check()


@contextmanager
def scope(purpose='interactive', *, budget=None, cancelled=None):
    existing = current()
    shared = existing or budget
    if shared is None:
        shared = Budget(DEFAULTS[purpose])
        shared.purpose = purpose
    if cancelled:
        shared.add_cancel_check(cancelled)
    token = _CURRENT.set(shared)
    try:
        shared.check()
        yield shared
    except OperationTerminated as exc:
        raise shared.terminate(exc)
    finally:
        if cancelled:
            shared.remove_cancel_check(cancelled)
        _CURRENT.reset(token)


def _signed_in_user(signature, args, kwargs):
    try:
        user = signature.bind_partial(*args, **kwargs).arguments.get('user')
    except TypeError:
        return None
    owner = user.get('id') if isinstance(user, dict) else None
    return owner if isinstance(owner, int) and not isinstance(owner, bool) and owner > 0 else None


def operation(purpose='interactive', *, origin='web'):
    """Wrap the function where it executes, preserving its public signature.

    When this starts a new operation and the function receives a `user` dict
    (the signed-in User of a web route, or the User of a daily run), the
    operation is attributed to that User with `origin`. Nested calls never
    attribute: an unattributed outer operation stays unattributed and its
    model requests fail closed.
    """
    def decorate(function):
        try:
            signature = inspect.signature(function)
        except (TypeError, ValueError):
            signature = None
        attributes = origin is not None and signature is not None and 'user' in signature.parameters

        @wraps(function)
        def guarded(*args, **kwargs):
            outermost = current() is None
            with scope(purpose) as shared:
                if outermost and attributes:
                    owner = _signed_in_user(signature, args, kwargs)
                    if owner is not None:
                        shared.attribute(owner, origin)
                return function(*args, **kwargs)
        return guarded
    return decorate
