"""Durable model usage ledger and per-User daily request quotas.

`model_transport.post_json` records one `model_calls` row per attempted POST
(parent process only; the exec helper never imports this module or `db`):

1. Reservation: one short `BEGIN IMMEDIATE` transaction counts the User's
   rows for the quota day, compares them with the quota and inserts the row,
   or refuses with `QuotaExceeded`. A locked or unusable ledger refuses with
   `UsageLedgerUnavailable`. Either way nothing is sent.
2. The provider call runs with no database connection open.
3. A second short transaction stores what the response stated
   (`responded`) or marks the outcome `unknown` (transport error, cancel,
   deadline). If that update fails the row stays `reserved`: unknown usage,
   never zero.

Quotas count requests and requested output tokens per calendar day in
`JOBWEAVER_QUOTA_TZ` (default: the server's local zone). They are volume
limits, not a monetary ceiling: price depends on the model, provider and prompt
size, and cost is reported only after a response, if at all. Attempts are never
refunded, and custom endpoints count like OpenRouter.
"""
from dataclasses import dataclass
from datetime import date, datetime, time as day_start, timedelta, timezone
from decimal import Decimal, InvalidOperation
import json
import logging
import math
import os
import re
import sqlite3
import time
from typing import Optional
from urllib.parse import urlsplit

from operation_budget import AttributionError, QuotaExceeded, UsageLedgerUnavailable, OperationTerminated

logger = logging.getLogger(__name__)

DEFAULT_ATTEMPTS = 300
DEFAULT_OUTPUT_TOKENS = 2_400_000
MAX_SETTING = 10 ** 9
ENV_ATTEMPTS = 'JOBWEAVER_QUOTA_REQUESTS'
ENV_OUTPUT_TOKENS = 'JOBWEAVER_QUOTA_OUTPUT_TOKENS'
ENV_ZONE = 'JOBWEAVER_QUOTA_TZ'
LOCK_WAIT = 5.0      # Upper bound of the reservation lock wait (also bounded by the deadline).
FINISH_WAIT = 2.0    # The update after a response never delays the caller longer than this.
OPENROUTER_HOST = 'openrouter.ai'

# Test seam: wall clock in epoch seconds. Quota days and timestamps use it.
_clock = time.time

_REQUEST_ID = re.compile(r'[A-Za-z0-9._:-]{1,128}')
_MODEL = re.compile(r'[A-Za-z0-9._:/@+-]{1,200}')
_REASON = re.compile(r'[A-Za-z0-9._:-]{1,64}')
# Only fixed code labels reach the ledger. Caller text (company, user or source names) never does.
LABELS = frozenset({'model', 'openrouter', 'custom', 'Posting analysis', 'Company research',
                    'Approved evidence selection', 'Letter plan', 'Letter verification', 'Grounded letter',
                    'Grounded edit'})
_MAX_COUNT = 10 ** 9


class QuotaSettingsError(OperationTerminated, ValueError):
    """Invalid quota environment settings. Fail at startup; refuse requests."""


@dataclass(frozen=True)
class Settings:
    attempts: int
    output_tokens: int
    zone_name: Optional[str]
    zone: object  # None means the server's local zone


def _positive(environ, name, default):
    raw = environ.get(name)
    if raw is None or not raw.strip():
        return default
    text = raw.strip()
    if not text.isascii() or not text.isdigit() or not 0 < int(text) <= MAX_SETTING:
        raise QuotaSettingsError(f'{name} must be a positive whole number up to {MAX_SETTING:,}.')
    return int(text)


def settings(environ=None) -> Settings:
    """Read and validate the quota environment. The backend calls this at startup."""
    environ = os.environ if environ is None else environ
    attempts = _positive(environ, ENV_ATTEMPTS, DEFAULT_ATTEMPTS)
    tokens = _positive(environ, ENV_OUTPUT_TOKENS, DEFAULT_OUTPUT_TOKENS)
    name = (environ.get(ENV_ZONE) or '').strip() or None
    zone = None
    if name:
        from zoneinfo import ZoneInfo
        try:
            zone = ZoneInfo(name)
        except (ValueError, OSError, LookupError) as exc:
            raise QuotaSettingsError(f'{ENV_ZONE} must be an IANA time zone name such as Europe/Vienna.') from exc
    return Settings(attempts, tokens, name, zone)


def quota_day(now: float, zone=None) -> tuple[str, int]:
    """Return (YYYY-MM-DD, whole seconds until the next quota day starts)."""
    if zone is None:
        local = datetime.fromtimestamp(now)
        reset = datetime.combine(local.date() + timedelta(days=1), day_start.min).timestamp()
    else:
        local = datetime.fromtimestamp(now, zone)
        reset = datetime.combine(local.date() + timedelta(days=1), day_start.min, tzinfo=zone).timestamp()
    return local.date().isoformat(), max(1, math.ceil(reset - now))


def _iso(now: float) -> str:
    return datetime.fromtimestamp(now, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')


def _duration(seconds: int) -> str:
    hours, minutes = seconds // 3600, (seconds % 3600 + 59) // 60
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return f'{hours} h {minutes} min' if hours else f'{max(1, minutes)} min'


def _connect(timeout: float) -> sqlite3.Connection:
    import db  # Lazy: the model helper loads model_transport.py as a script and never reaches this.
    conn = sqlite3.connect(db.DB_PATH, timeout=max(0.0, timeout), isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    return conn


def _ensure(conn):
    import db
    db.ensure_model_usage_schema(conn)


def route_of(url: str) -> tuple[str, str]:
    host = (urlsplit(url).hostname or '').lower()
    return ('openrouter' if host == OPENROUTER_HOST else 'custom'), host[:253]


def _clean_model(value) -> str:
    text = value if isinstance(value, str) else ''
    text = ''.join(ch for ch in text if _MODEL.fullmatch(ch))[:200]
    return text or 'unknown'


def _clean_label(value) -> str:
    return value if isinstance(value, str) and value in LABELS else 'model'


def _limits(conn, user_id, config):
    row = conn.execute('SELECT daily_attempts, daily_output_tokens FROM user_model_quotas WHERE user_id = ?',
                       (user_id,)).fetchone()
    attempts = row['daily_attempts'] if row and row['daily_attempts'] is not None else config.attempts
    tokens = row['daily_output_tokens'] if row and row['daily_output_tokens'] is not None else config.output_tokens
    return attempts, tokens, bool(row and (row['daily_attempts'] is not None or row['daily_output_tokens'] is not None))


def _used(conn, user_id, day):
    row = conn.execute('''SELECT COUNT(*) AS attempts, COALESCE(SUM(requested_output_tokens), 0) AS tokens
        FROM model_calls WHERE user_id = ? AND day = ?''', (user_id, day)).fetchone()
    return row['attempts'], row['tokens']


def reserve(budget, *, url, payload, label, prompt_bytes, payload_bytes, output_tokens) -> int:
    """Check the owner's daily quota and insert the reservation row atomically.

    Raises QuotaExceeded or UsageLedgerUnavailable; nothing may be sent then.
    """
    config = settings()
    now = _clock()
    day, reset = quota_day(now, config.zone)
    route, host = route_of(url)
    wait = min(LOCK_WAIT, max(0.0, budget.deadline - time.monotonic()))
    unavailable = ('The model usage ledger is busy or unavailable, so this request was not sent. '
                   'Try again shortly.')
    try:
        conn = _connect(wait)
    except sqlite3.Error as exc:
        raise UsageLedgerUnavailable(unavailable) from exc
    try:
        conn.execute('BEGIN IMMEDIATE')
        _ensure(conn)
        attempts_limit, tokens_limit, _ = _limits(conn, budget.owner, config)
        attempts, tokens = _used(conn, budget.owner, day)
        if attempts + 1 > attempts_limit:
            raise QuotaExceeded(f'Daily model request quota reached: {attempts:,} of {attempts_limit:,} requests '
                                f'used today. This request was not sent. The quota resets in {_duration(reset)}.',
                                reset)
        if tokens + output_tokens > tokens_limit:
            raise QuotaExceeded(f'Daily requested output token quota reached: {tokens:,} of {tokens_limit:,} '
                                f'requested output tokens used today, and this request asks for {output_tokens:,}. '
                                f'It was not sent. The quota resets in {_duration(reset)}.', reset)
        cursor = conn.execute('''INSERT INTO model_calls
            (user_id, origin, operation_id, task_id, purpose, label, route, endpoint_host, requested_model, day,
             reserved_at, prompt_bytes, payload_bytes, requested_output_tokens, outcome)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved')''',
            (budget.owner, budget.origin, budget.operation_id, budget.task_id, budget.purpose, _clean_label(label),
             route, host, _clean_model(payload.get('model')), day, _iso(now), prompt_bytes, payload_bytes,
             output_tokens))
        conn.execute('COMMIT')
        return cursor.lastrowid
    except QuotaExceeded:
        conn.execute('ROLLBACK')
        raise
    except sqlite3.IntegrityError as exc:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        # The owning User does not exist (for example, deleted during the operation).
        raise AttributionError('Model request refused: the owning User no longer exists. Nothing was sent.') from exc
    except sqlite3.Error as exc:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise UsageLedgerUnavailable(unavailable) from exc
    finally:
        conn.close()


def _reject_constant(_):
    raise ValueError('non-finite number')


def _text(value, pattern):
    return value if isinstance(value, str) and pattern.fullmatch(value) else None


def _count(value):
    return value if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= _MAX_COUNT else None


def _cost(value):
    """Exact decimal text, or None. An explicit zero is stored as '0'."""
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        return None
    try:
        number = Decimal(value)
        if not number.is_finite() or number < 0 or number > MAX_SETTING or (number and number.adjusted() < -30):
            return None
    except (InvalidOperation, ValueError):
        return None
    if number == 0:
        return '0'
    text = format(number, 'f')
    return text if len(text) <= 64 else None


def _section(mapping, key):
    value = mapping.get(key) if isinstance(mapping, dict) else None
    return value if isinstance(value, dict) else {}


def response_fields(route: str, status, content: bytes) -> dict:
    """Fields the response states. Anything absent, malformed or out of range stays None.

    Never raises: an unexpected parse failure degrades to NULL response fields.
    """
    try:
        return _response_fields(route, status, content)
    except Exception as exc:
        logger.warning('Model usage response fields unavailable (%s).', type(exc).__name__)
        return {}


def _response_fields(route, status, content):
    fields = dict(http_status=status if isinstance(status, int) and not isinstance(status, bool) else None,
                  response_bytes=len(content) if isinstance(content, (bytes, bytearray)) else None,
                  provider_request_id=None, served_model=None, finish_reason=None, prompt_tokens=None,
                  completion_tokens=None, total_tokens=None, cached_tokens=None, reasoning_tokens=None,
                  reported_cost=None, cost_unit=None, is_byok=None)
    try:
        data = json.loads(content, parse_float=Decimal, parse_constant=_reject_constant)
    except (ValueError, TypeError, RecursionError):
        return fields
    if not isinstance(data, dict):
        return fields
    fields['provider_request_id'] = _text(data.get('id'), _REQUEST_ID)
    fields['served_model'] = _text(data.get('model'), _MODEL)
    choices = data.get('choices')
    if isinstance(choices, list) and choices and isinstance(choices[0], dict):
        fields['finish_reason'] = _text(choices[0].get('finish_reason'), _REASON)
    usage = _section(data, 'usage')
    for name in ('prompt_tokens', 'completion_tokens', 'total_tokens'):
        fields[name] = _count(usage.get(name))
    fields['cached_tokens'] = _count(_section(usage, 'prompt_tokens_details').get('cached_tokens'))
    fields['reasoning_tokens'] = _count(_section(usage, 'completion_tokens_details').get('reasoning_tokens'))
    fields['reported_cost'] = _cost(usage.get('cost'))
    if fields['reported_cost'] is not None:
        fields['cost_unit'] = 'openrouter_credits' if route == 'openrouter' else 'endpoint_reported'
    if isinstance(usage.get('is_byok'), bool):
        fields['is_byok'] = int(usage['is_byok'])
    return fields


def finish(call_id: int, outcome: str, fields: Optional[dict] = None) -> bool:
    """Record the outcome. Never raises: a failed update leaves the row 'reserved' (unknown)."""
    values = dict(fields or {}, outcome=outcome, finished_at=_iso(_clock()))
    columns = ', '.join(f'{name} = ?' for name in values)
    try:
        conn = _connect(FINISH_WAIT)
        try:
            conn.execute(f"UPDATE model_calls SET {columns} WHERE id = ? AND outcome = 'reserved'",
                         (*values.values(), call_id))
        finally:
            conn.close()
        return True
    except Exception as exc:
        logger.warning('Model usage row %s stays reserved (outcome unknown): ledger update failed (%s).',
                       call_id, type(exc).__name__)
        return False


RETENTION_DAYS = 400


def prune(days: int = RETENTION_DAYS) -> int:
    """Delete ledger rows reserved more than `days` ago. The backend runs this at startup."""
    cutoff = _iso(_clock() - days * 86400)
    conn = _connect(LOCK_WAIT)
    try:
        conn.execute('BEGIN IMMEDIATE')
        _ensure(conn)
        count = conn.execute('DELETE FROM model_calls WHERE reserved_at < ?', (cutoff,)).rowcount
        conn.execute('COMMIT')
        return count
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


# --- administration and reports (manage_users.py, GET /api/usage/today) ------------------------------------

def set_quota(user_id: int, *, attempts: Optional[int] = None, output_tokens: Optional[int] = None,
              default: bool = False) -> None:
    """Per-User override. `default=True` removes it; a None field keeps its current override."""
    for value in (attempts, output_tokens):
        if value is not None and (isinstance(value, bool) or not isinstance(value, int) or not 0 < value <= MAX_SETTING):
            raise ValueError(f'Quota values must be positive whole numbers up to {MAX_SETTING:,}.')
    conn = _connect(LOCK_WAIT)
    try:
        conn.execute('BEGIN IMMEDIATE')
        _ensure(conn)
        if default:
            conn.execute('DELETE FROM user_model_quotas WHERE user_id = ?', (user_id,))
        else:
            conn.execute('''INSERT INTO user_model_quotas (user_id, daily_attempts, daily_output_tokens, updated_at)
                VALUES (?, ?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET
                daily_attempts = COALESCE(excluded.daily_attempts, daily_attempts),
                daily_output_tokens = COALESCE(excluded.daily_output_tokens, daily_output_tokens),
                updated_at = excluded.updated_at''', (user_id, attempts, output_tokens, _iso(_clock())))
        conn.execute('COMMIT')
    except BaseException:
        if conn.in_transaction:
            conn.execute('ROLLBACK')
        raise
    finally:
        conn.close()


def quota_status(user_id: int) -> dict:
    """Today's quota use for one User, in the configured quota zone."""
    config = settings()
    day, reset = quota_day(_clock(), config.zone)
    conn = _connect(LOCK_WAIT)
    try:
        _ensure(conn)
        attempts_limit, tokens_limit, override = _limits(conn, user_id, config)
        attempts, tokens = _used(conn, user_id, day)
    finally:
        conn.close()
    return dict(day=day, zone=config.zone_name or 'server local time', resets_in_seconds=reset,
                requests_used=attempts, requests_limit=attempts_limit,
                requested_output_tokens_used=tokens, requested_output_tokens_limit=tokens_limit,
                override=override, monetary_ceiling=False)


def usage_report(user_id: Optional[int] = None, day: Optional[str] = None) -> list[dict]:
    """Per-User coverage for one day. Costs are summed only over rows that reported one, per unit."""
    if day is None:
        day = quota_day(_clock(), settings().zone)[0]
    if date.fromisoformat(day).isoformat() != day:
        raise ValueError('day must be a calendar date written YYYY-MM-DD')
    conn = _connect(LOCK_WAIT)
    try:
        _ensure(conn)
        where, params = 'day = ?', [day]
        if user_id is not None:
            where, params = where + ' AND user_id = ?', params + [user_id]
        rows = conn.execute(f'''SELECT user_id, outcome, requested_output_tokens, completion_tokens,
            reported_cost, cost_unit FROM model_calls WHERE {where} ORDER BY user_id, id''', params).fetchall()
    finally:
        conn.close()
    report = {}
    for row in rows:
        entry = report.setdefault(row['user_id'], dict(
            user_id=row['user_id'], day=day, rows=0, responded=0, unknown=0, without_response=0,
            rows_with_cost=0, rows_without_cost=0, rows_with_completion_tokens=0,
            requested_output_tokens=0, reported_completion_tokens=0, reported_cost={}))
        entry['rows'] += 1
        entry['requested_output_tokens'] += row['requested_output_tokens']
        if row['outcome'] == 'responded':
            entry['responded'] += 1
        else:
            entry['without_response'] += 1
            entry['unknown'] += row['outcome'] == 'unknown'
        if row['completion_tokens'] is not None:
            entry['rows_with_completion_tokens'] += 1
            entry['reported_completion_tokens'] += row['completion_tokens']
        if row['reported_cost'] is None:
            entry['rows_without_cost'] += 1
        else:
            entry['rows_with_cost'] += 1
            unit = row['cost_unit'] or 'unspecified'
            entry['reported_cost'][unit] = entry['reported_cost'].get(unit, Decimal(0)) + Decimal(row['reported_cost'])
    for entry in report.values():
        entry['reported_cost'] = {unit: format(total, 'f') if total else '0'
                                  for unit, total in entry['reported_cost'].items()}
    return list(report.values())
