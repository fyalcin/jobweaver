"""Explicit inline fixtures for legacy provider unit tests; never production."""
from contextlib import ExitStack, contextmanager
from unittest.mock import patch
import requests
import model_transport
import model_usage

FICTIONAL_OWNER = 4242


class MemoryLedger:
    """In-memory stand-in for `model_usage` with the same reserve/finish surface.

    Legacy tests stay focused on provider behaviour: no database, no daily quota.
    Ledger and quota behaviour is tested against the real SQLite ledger.
    """

    route_of = staticmethod(model_usage.route_of)
    response_fields = staticmethod(model_usage.response_fields)

    def __init__(self):
        self.rows = []

    def reserve(self, budget, **fields):
        self.rows.append(dict(fields, owner=budget.owner, origin=budget.origin, outcome='reserved'))
        return len(self.rows) - 1

    def finish(self, call, outcome, fields=None):
        self.rows[call].update(fields or {}, outcome=outcome)
        return True


@contextmanager
def fictional_ledger(owner=FICTIONAL_OWNER):
    """Attribute unowned operations to a fictional User and record calls in memory."""
    ledger = MemoryLedger()
    with patch.object(model_transport, '_ledger', ledger), patch.object(model_transport, '_fixture_owner', owner):
        yield ledger


class _Fixture:
    """Supports both `with inline_transport():` and module-level start()/stop()."""

    def __init__(self):
        self._stack = None
        self.ledger = None

    def start(self):
        self._stack = ExitStack()
        self.ledger = self._stack.enter_context(fictional_ledger())
        self._stack.enter_context(patch.object(
            model_transport, '_post_impl', side_effect=lambda *args, **kwargs: requests.post(*args, **kwargs)))
        return self

    def stop(self):
        self._stack.close()

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.stop()


def inline_transport():
    return _Fixture()
