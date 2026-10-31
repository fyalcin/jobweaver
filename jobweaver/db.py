"""
db.py — SQLite storage layer for Jobweaver.

Schema
------
users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    display_name TEXT,
    password_hash TEXT,                    -- NULL until set via manage_users.py
    telegram_chat_id TEXT,
    created_at TEXT
)

jobs (
    user_id INTEGER NOT NULL,              -- owner; FK → users.id
    id TEXT,                               -- source-prefixed job id
    job_url TEXT,
    title TEXT, company TEXT, date_scraped TEXT, source TEXT,
    requires_german INTEGER, match_score INTEGER,
    applied INTEGER DEFAULT 0,
    is_one_off INTEGER DEFAULT 0,          -- kept for completeness; always 0 now
    application_date TEXT, application_method TEXT,
    response_status TEXT, company_contact TEXT,
    data TEXT NOT NULL,                    -- full job dict serialised as JSON
    PRIMARY KEY (user_id, id),
    UNIQUE (user_id, job_url)
)

scraping_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT, message TEXT, level TEXT,
    user_id INTEGER                        -- NULL = legacy/global entries
)

async_tasks (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    payload TEXT,
    result TEXT,
    logs TEXT,
    total INTEGER,
    processed INTEGER,
    failed INTEGER,
    cancelled INTEGER DEFAULT 0,
    user_id INTEGER                        -- owning user (NULL = legacy)
)

model_calls / user_model_quotas: the durable model usage ledger and per-User
daily quota overrides; see `ensure_model_usage_schema` and `model_usage.py`.

The `data` column is the authoritative record; the other columns are indexed
copies used for fast WHERE / ORDER BY queries.  When a row is updated (e.g.
applied flag, application_date) both the indexed column and the JSON blob are
kept in sync.  All job/task/log access is scoped by `user_id` so multiple
household members each see only their own pipeline.
"""

import json
import logging
import os
import sqlite3
import time
from datetime import datetime
from typing import Any, Optional

import pandas as pd
from jobweaver import PROJECT_ROOT
from jobweaver.german import normalize_german_level, requires_german
from jobweaver.user_assets import DATA_DIR

logger = logging.getLogger(__name__)

# Columns that have their own DB column (and must be kept in sync with `data`)
INDEXED_COLS = {
    "id", "job_url", "title", "company", "date_scraped", "source",
    "requires_german", "german_level", "match_score", "match_rating", "match_checks", "applied", "status", "is_one_off",
    "application_date", "application_method", "response_status", "company_contact",
    "processed", "cv_profile_override", "user_id",
}

MAX_LOG_ROWS = 500  # keep last N scraping log entries

# Module-level DB path (overridable for tests via set_db_path)
DB_PATH = os.path.join(DATA_DIR, "jobweaver.db")

DEFAULT_USER_USERNAME = "admin"


def set_db_path(path: str) -> None:
    """Point the storage layer at a different SQLite file (used by tests)."""
    global DB_PATH
    DB_PATH = path


# ---------------------------------------------------------------------------
# Connection helpers
# ---------------------------------------------------------------------------

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")   # better concurrent-read support
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


# ---------------------------------------------------------------------------
# Schema creation & JSON migration
# ---------------------------------------------------------------------------

def _ensure_default_user(conn: sqlite3.Connection) -> int:
    """Create the default user (admin) if the users table is empty.

    Existing single-user data migrates to this account.  Returns its id.
    The account starts with password_hash=NULL; `manage_users.py passwd`
    sets a real password (login requires one).
    """
    row = conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()
    if row:
        return row["id"]
    username = DEFAULT_USER_USERNAME
    while conn.execute('SELECT 1 FROM retired_usernames WHERE username = ?', (username,)).fetchone():
        import secrets
        username = DEFAULT_USER_USERNAME + '-' + secrets.token_hex(8)
    conn.execute(
        "INSERT INTO users (username, display_name, password_hash, created_at) VALUES (?, ?, NULL, ?)",
        (username, username.capitalize(), datetime.now().isoformat()),
    )
    logger.info("Created default user '%s' (set a password via python -m jobweaver.manage_users)", username)
    return conn.execute("SELECT id FROM users ORDER BY id LIMIT 1").fetchone()["id"]


def _jobs_needs_user_migration(conn: sqlite3.Connection) -> bool:
    """True when a jobs table exists but predates the multi-user schema."""
    exists = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='jobs'"
    ).fetchone()
    if not exists:
        return False
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    return "user_id" not in cols


def _rebuild_jobs_table_with_user(conn: sqlite3.Connection, default_user_id: int) -> None:
    """One-time rebuild: add user_id, switch PK to (user_id, id) and the URL
    uniqueness to (user_id, job_url). All existing rows go to the default user.
    Tolerates older schemas that are missing newer columns (defaults applied)."""
    logger.info("Migrating jobs table to multi-user schema (all rows → user %s)…", default_user_id)
    conn.execute("ALTER TABLE jobs RENAME TO jobs_legacy")
    _create_jobs_table(conn)
    legacy_cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs_legacy)")}
    target_cols = [
        "id", "job_url", "title", "company", "date_scraped", "source",
        "requires_german", "german_level", "match_score", "applied", "status",
        "is_one_off", "application_date", "application_method", "response_status",
        "company_contact", "processed", "data",
    ]
    # Fallbacks for columns absent from older schema versions
    col_defaults = {
        "requires_german": "0",
        "german_level": "'unknown'",
        "applied": "0",
        "status": "'new'",
        "is_one_off": "0",
        "processed": "1",
    }
    select_parts = []
    for col in target_cols:
        if col in legacy_cols:
            select_parts.append(col)
        else:
            select_parts.append(f"{col_defaults[col]} AS {col}")
    conn.execute(
        f"INSERT INTO jobs (user_id, {', '.join(target_cols)}) "
        f"SELECT :uid AS user_id, {', '.join(select_parts)} FROM jobs_legacy",
        {"uid": default_user_id},
    )
    conn.execute("DROP TABLE jobs_legacy")
    logger.info("jobs table migrated to multi-user schema.")


def _create_jobs_table(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS jobs (
            user_id            INTEGER NOT NULL,
            id                 TEXT,
            job_url            TEXT,
            title              TEXT,
            company            TEXT,
            date_scraped       TEXT,
            source             TEXT,
            requires_german    INTEGER DEFAULT 0,
            german_level       TEXT DEFAULT 'unknown',
            match_score        INTEGER,
            match_rating       TEXT,
            match_checks       TEXT,
            applied            INTEGER DEFAULT 0,
            status             TEXT DEFAULT 'new',
            is_one_off         INTEGER DEFAULT 0,
            application_date   TEXT,
            application_method TEXT,
            response_status    TEXT,
            company_contact    TEXT,
            processed          INTEGER DEFAULT 1,
            data               TEXT NOT NULL,
            PRIMARY KEY (user_id, id),
            UNIQUE (user_id, job_url),
            FOREIGN KEY (user_id) REFERENCES users(id)
        )
    """)


MODEL_USAGE_SCHEMA = (
    # One row per attempted model POST. Reservation columns are NOT NULL; every
    # response-derived column stays NULL unless the response stated it. Never
    # store prompts, responses, error bodies, headers, full URLs or keys here.
    """CREATE TABLE IF NOT EXISTS model_calls (
        id                      INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        origin                  TEXT NOT NULL,
        operation_id            TEXT NOT NULL,
        task_id                 TEXT,
        purpose                 TEXT NOT NULL,
        label                   TEXT NOT NULL,
        route                   TEXT NOT NULL,
        endpoint_host           TEXT NOT NULL,
        requested_model         TEXT NOT NULL,
        day                     TEXT NOT NULL,
        reserved_at             TEXT NOT NULL,
        prompt_bytes            INTEGER NOT NULL,
        payload_bytes           INTEGER NOT NULL,
        requested_output_tokens INTEGER NOT NULL,
        outcome                 TEXT NOT NULL DEFAULT 'reserved',
        finished_at             TEXT,
        http_status             INTEGER,
        response_bytes          INTEGER,
        provider_request_id     TEXT,
        served_model            TEXT,
        finish_reason           TEXT,
        prompt_tokens           INTEGER,
        completion_tokens       INTEGER,
        total_tokens            INTEGER,
        cached_tokens           INTEGER,
        reasoning_tokens        INTEGER,
        reported_cost           TEXT,
        cost_unit               TEXT,
        is_byok                 INTEGER
    )""",
    "CREATE INDEX IF NOT EXISTS idx_model_calls_user_day ON model_calls(user_id, day)",
    """CREATE TABLE IF NOT EXISTS user_model_quotas (
        user_id             INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        daily_attempts      INTEGER,
        daily_output_tokens INTEGER,
        updated_at          TEXT NOT NULL
    )""",
)


def ensure_model_usage_schema(conn: sqlite3.Connection) -> None:
    """Additive and idempotent; cron and CLI runs may never call init_db."""
    for statement in MODEL_USAGE_SCHEMA:
        conn.execute(statement)


def init_db() -> None:
    """Create tables (if needed), migrate to the multi-user schema, then
    auto-import legacy JSON files on first run."""
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            username         TEXT UNIQUE NOT NULL,
            display_name     TEXT,
            password_hash    TEXT,
            telegram_chat_id TEXT,
            created_at       TEXT
        )
    """)
    conn.execute('''CREATE TABLE IF NOT EXISTS user_sessions (
        token_hash TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at INTEGER NOT NULL
    )''')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_user_sessions_user ON user_sessions(user_id)')
    conn.execute('CREATE TABLE IF NOT EXISTS retired_usernames (username TEXT PRIMARY KEY)')
    conn.execute('''CREATE TABLE IF NOT EXISTS login_attempts (
        bucket TEXT PRIMARY KEY, started_at INTEGER NOT NULL, attempts INTEGER NOT NULL
    )''')
    default_user_id = _ensure_default_user(conn)

    if _jobs_needs_user_migration(conn):
        _rebuild_jobs_table_with_user(conn, default_user_id)
    else:
        _create_jobs_table(conn)

    # Schema Migration for `status` column (legacy single-user installs)
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN status TEXT DEFAULT 'new'")
        conn.execute("UPDATE jobs SET status = 'applied' WHERE applied = 1")
        conn.execute("UPDATE jobs SET status = 'new' WHERE applied = 0 OR applied IS NULL")
    except sqlite3.OperationalError:
        pass  # Column already exists
    # Schema Migration for `processed` column
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN processed INTEGER DEFAULT 1")
        conn.execute("UPDATE jobs SET processed = 1 WHERE processed IS NULL")
    except sqlite3.OperationalError:
        pass  # Column already exists
    try:
        conn.execute("ALTER TABLE jobs ADD COLUMN german_level TEXT DEFAULT 'unknown'")
        conn.execute("UPDATE jobs SET german_level = CASE WHEN requires_german = 1 THEN 'unknown' ELSE 'none' END")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.execute("""
        CREATE TABLE IF NOT EXISTS scraping_logs (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            message   TEXT,
            level     TEXT,
            user_id   INTEGER
        )
    """)
    try:
        conn.execute("ALTER TABLE scraping_logs ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.execute("""
        CREATE TABLE IF NOT EXISTS async_tasks (
            id          TEXT PRIMARY KEY,
            kind        TEXT NOT NULL,
            status      TEXT NOT NULL,
            created_at  REAL NOT NULL,
            updated_at  REAL NOT NULL,
            payload     TEXT,
            result      TEXT,
            logs        TEXT,
            total       INTEGER,
            processed   INTEGER,
            failed      INTEGER,
            cancelled   INTEGER DEFAULT 0,
            user_id     INTEGER
        )
    """)
    try:
        conn.execute("ALTER TABLE async_tasks ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError:
        pass  # Column already exists

    for column in ("stage TEXT", "request_key TEXT"):
        try:
            conn.execute(f"ALTER TABLE async_tasks ADD COLUMN {column}")
        except sqlite3.OperationalError:
            pass  # Column already exists

    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_async_tasks_kind_status ON async_tasks(kind, status, created_at)"
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_jobs_user         ON jobs(user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_date_scraped      ON jobs(user_id, date_scraped)")
    for column in ("match_rating TEXT", "match_checks TEXT"):
        if column.split()[0] not in {r[1] for r in conn.execute('PRAGMA table_info(jobs)')}:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_match_rating ON jobs(user_id, match_rating)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_match_score       ON jobs(user_id, match_score)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_status            ON jobs(user_id, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requires_german   ON jobs(user_id, requires_german)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_german_level      ON jobs(user_id, german_level)")
    ensure_model_usage_schema(conn)
    conn.commit()
    _migrate_from_json(conn, default_user_id)
    conn.close()
    logger.info("DB initialised at %s", DB_PATH)


def _migrate_from_json(conn: sqlite3.Connection, default_user_id: int) -> None:
    """
    One-time import of all_jobs_persistent.json into SQLite.
    Runs only when the jobs table is empty AND the JSON file exists.
    After import the JSON file is renamed to *.json.migrated so it
    won't be re-imported on the next startup.
    """
    count = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    if count > 0:
        return  # Already populated — skip migration

    base_dir = str(PROJECT_ROOT)
    main_json = os.path.join(base_dir, "all_jobs_persistent.json")

    if not os.path.exists(main_json):
        logger.info("No all_jobs_persistent.json found — starting with empty DB.")
        return

    try:
        with open(main_json, "r", encoding="utf-8") as f:
            jobs = json.load(f)
        imported = 0
        for job in jobs:
            try:
                _upsert_job_conn(conn, job, is_one_off=False, user_id=default_user_id)
                imported += 1
            except Exception as e:
                logger.warning("Skipping job during migration: %s", e)
        conn.commit()
        logger.info("Migrated %d jobs from all_jobs_persistent.json", imported)
        os.rename(main_json, main_json + ".migrated")
    except Exception as e:
        logger.error("Migration failed: %s", e)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _to_bool_int(v) -> int:
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(bool(v))
    if isinstance(v, str):
        return 1 if v.strip().lower() in ("true", "yes", "1") else 0
    return 0


def _make_row(job: dict, is_one_off: bool = False, user_id: Optional[int] = None) -> dict:
    """Build the dict that maps directly to INSERT column values."""
    job_copy = dict(job)
    job_copy["is_one_off"] = is_one_off
    if user_id is not None:
        job_copy["user_id"] = user_id
    return {
        "user_id":           int(job_copy["user_id"]),
        "id":                 str(job_copy.get("id") or ""),
        # Missing URLs are NULL for every source; incomplete observations must not collide.
        "job_url":            job_copy.get("job_url") or None,
        "title":              job_copy.get("title"),
        "company":            job_copy.get("company"),
        "date_scraped":       job_copy.get("date_scraped"),
        "source":             job_copy.get("source"),
        "requires_german":    int(requires_german(job_copy.get("german_level", job_copy.get("requires_german")))),
        "german_level":       normalize_german_level(job_copy.get("german_level", job_copy.get("requires_german"))),
        "match_score":        job_copy.get("match_score"),
        "match_rating":       job_copy.get("match_rating"),
        "match_checks":       json.dumps(job_copy.get("match_checks") or [], ensure_ascii=False),
        "applied":            _to_bool_int(job_copy.get("status") == "applied" or job_copy.get("applied", False)),
        "status":             job_copy.get("status", "new"),
        "is_one_off":         int(is_one_off),
        "application_date":   job_copy.get("application_date"),
        "application_method": job_copy.get("application_method"),
        "response_status":    job_copy.get("response_status"),
        "company_contact":    job_copy.get("company_contact"),
        "processed":          int(job_copy.get("processed", 1)),
        "data":               json.dumps(job_copy, ensure_ascii=False, default=str),
    }


def _merge_row(row: sqlite3.Row) -> dict:
    """
    Reconstruct the full job dict from a DB row.  Indexed columns override
    whatever is in the JSON blob so updates are always reflected.
    """
    d = json.loads(row["data"] or "{}")
    # Indexed columns are always up-to-date — apply them on top
    for col in INDEXED_COLS:
        try:
            val = row[col]
        except IndexError:
            continue
        if col in ("requires_german", "applied", "is_one_off"):
            d[col] = bool(val) if val is not None else False
        elif col == "match_checks":
            d[col] = json.loads(val) if val else d.get(col, [])
        elif col == "processed":
            d[col] = int(val) if val is not None else 1
        else:
            d[col] = val
    return d


def _upsert_job_conn(conn: sqlite3.Connection, job: dict, is_one_off: bool = False, user_id: Optional[int] = None) -> None:
    if user_id is None:
        raise ValueError("user_id is required to store a job")
    if not conn.in_transaction:
        conn.execute('BEGIN IMMEDIATE')
    url = job.get('job_url')
    matches = conn.execute('SELECT * FROM jobs WHERE user_id=? AND (id=? OR (job_url=? AND ? IS NOT NULL))',
                           (user_id, str(job.get('id', '')), url or None, url or None)).fetchall()
    if len(matches) > 1:
        raise ValueError('Posting identity conflicts with two existing jobs; review before merging')
    previous = matches[0] if matches else None
    if previous:
        old = _merge_row(previous)
        merged = {**old, **job, 'id': old['id']}
        # Ingestion never owns application state. Explicit user edits use update_job_fields.
        for key in ('status', 'applied', 'application_date', 'application_method', 'response_status'):
            merged[key] = old.get(key)
        # A later scrape that found no company apply link (actor hiccup, fallback actor) must not
        # erase one found earlier.
        new_link = job.get('apply_url')
        if (new_link is None or new_link != new_link or new_link == '') and old.get('apply_url'):
            merged['apply_url'] = old['apply_url']
            merged['apply_type'] = old.get('apply_type')
        if job.get('raw_description') and job['raw_description'] != old.get('raw_description', old.get('description')):
            merged['posting_history'] = [*(old.get('posting_history') or []),
                {'raw_description': old.get('raw_description', old.get('description')), 'last_seen': old.get('last_seen')}]
        job = merged
    row = _make_row(job, is_one_off, user_id)
    conn.execute("""
        INSERT INTO jobs
            (user_id, id, job_url, title, company, date_scraped, source,
             requires_german, german_level, match_score, match_rating, match_checks, applied, status, is_one_off,
             application_date, application_method, response_status,
             company_contact, processed, data)
        VALUES
            (:user_id, :id, :job_url, :title, :company, :date_scraped, :source,
             :requires_german, :german_level, :match_score, :match_rating, :match_checks, :applied, :status, :is_one_off,
             :application_date, :application_method, :response_status,
             :company_contact, :processed, :data)
        ON CONFLICT(user_id, id) DO UPDATE SET
            job_url=excluded.job_url, title=excluded.title, company=excluded.company,
            date_scraped=excluded.date_scraped, source=excluded.source,
            requires_german=excluded.requires_german, german_level=excluded.german_level,
            match_score=excluded.match_score, match_rating=excluded.match_rating, match_checks=excluded.match_checks, applied=excluded.applied, status=excluded.status,
            application_date=excluded.application_date, application_method=excluded.application_method,
            response_status=excluded.response_status, company_contact=excluded.company_contact,
            processed=excluded.processed, data=excluded.data
    """, row)


def get_job_by_url(url: str, user_id: int):
    conn = get_conn()
    try:
        row = conn.execute('SELECT * FROM jobs WHERE user_id=? AND job_url=?', (user_id, url)).fetchone()
        return _merge_row(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def _row_to_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "username": row["username"],
        "display_name": row["display_name"] or row["username"],
        "password_hash": row["password_hash"],
        "telegram_chat_id": row["telegram_chat_id"],
        "created_at": row["created_at"],
    }


def create_user(username: str, password_hash: Optional[str] = None,
                display_name: Optional[str] = None, telegram_chat_id: Optional[str] = None) -> dict:
    from jobweaver.user_assets import normalize_username, user_profile_dir
    username = normalize_username(username)
    conn = get_conn()
    try:
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('SELECT 1 FROM retired_usernames WHERE username = ?', (username,)).fetchone():
            raise ValueError('This username was retired to protect retained profile files. Choose another username.')
        if os.path.lexists(user_profile_dir(username)):
            raise ValueError('Profile files already exist for this username. Choose another username; existing files were preserved.')
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, telegram_chat_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (username, display_name or username, password_hash, telegram_chat_id, datetime.now().isoformat()),
        )
        conn.commit()
    except sqlite3.IntegrityError as e:
        raise ValueError(f"username '{username}' already exists") from e
    else:
        user = get_user_by_username(username, conn=conn)
    finally:
        conn.close()
    return user


def _get_user(conn: sqlite3.Connection, sql: str, params: tuple) -> Optional[dict]:
    row = conn.execute(sql, params).fetchone()
    return _row_to_user(row) if row else None


def get_user_by_id(user_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    own = conn is None
    conn = conn or get_conn()
    user = _get_user(conn, "SELECT * FROM users WHERE id = ?", (user_id,))
    if own:
        conn.close()
    return user


def get_user_by_username(username: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    own = conn is None
    conn = conn or get_conn()
    user = _get_user(conn, "SELECT * FROM users WHERE username = ?", (username.strip().lower(),))
    if own:
        conn.close()
    return user


def get_user_by_telegram_chat(chat_id: str, conn: Optional[sqlite3.Connection] = None) -> Optional[dict]:
    own = conn is None
    conn = conn or get_conn()
    user = _get_user(conn, "SELECT * FROM users WHERE telegram_chat_id = ?", (str(chat_id),))
    if own:
        conn.close()
    return user


def list_users() -> list:
    conn = get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
    conn.close()
    return [_row_to_user(r) for r in rows]


def update_user_fields(user_id: int, **fields) -> bool:
    """Update allowed user columns (password_hash, display_name, telegram_chat_id)."""
    allowed = {"password_hash", "display_name", "telegram_chat_id"}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    set_clause = ", ".join(f"{k} = ?" for k in updates)
    conn = get_conn()
    cur = conn.execute(f"UPDATE users SET {set_clause} WHERE id = ?", (*updates.values(), user_id))
    if 'password_hash' in updates:
        conn.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def create_session(user_id: int, token_hash: str, expires_at: int, now: int, credential_hash=None) -> bool:
    conn = get_conn()
    try:
        with conn:
            conn.execute('DELETE FROM user_sessions WHERE expires_at <= ?', (now,))
            if credential_hash is None:
                conn.execute('INSERT INTO user_sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)',
                             (token_hash, user_id, expires_at))
                return True
            result = conn.execute('''INSERT INTO user_sessions (token_hash, user_id, expires_at)
                SELECT ?, id, ? FROM users WHERE id = ? AND password_hash = ?''',
                (token_hash, expires_at, user_id, credential_hash))
            return result.rowcount == 1
    finally:
        conn.close()


def session_user(token_hash: str, now: int) -> Optional[int]:
    conn = get_conn()
    try:
        row = conn.execute('SELECT user_id FROM user_sessions WHERE token_hash = ? AND expires_at > ?',
                           (token_hash, now)).fetchone()
        return row['user_id'] if row else None
    finally:
        conn.close()


def revoke_session(token_hash: str) -> None:
    conn = get_conn()
    try:
        with conn:
            conn.execute('DELETE FROM user_sessions WHERE token_hash = ?', (token_hash,))
    finally:
        conn.close()


def upgrade_password_hash(user_id: int, previous: str, replacement: str) -> bool:
    conn = get_conn()
    try:
        with conn:
            result = conn.execute('UPDATE users SET password_hash = ? WHERE id = ? AND password_hash = ?',
                                  (replacement, user_id, previous))
            if result.rowcount:
                conn.execute('DELETE FROM user_sessions WHERE user_id = ?', (user_id,))
            return result.rowcount == 1
    finally:
        conn.close()


def reserve_login_attempt(buckets: dict[str, int], now: int, window=60) -> int:
    """Atomically reserve hash work. Return retry seconds when any bucket is full."""
    conn = get_conn()
    try:
        with conn:
            conn.execute('BEGIN IMMEDIATE')
            conn.execute('DELETE FROM login_attempts WHERE started_at <= ?', (now - window,))
            for bucket, maximum in buckets.items():
                row = conn.execute('SELECT * FROM login_attempts WHERE bucket = ?', (bucket,)).fetchone()
                if row and row['attempts'] >= maximum:
                    return max(1, row['started_at'] + window - now)
            for bucket in buckets:
                conn.execute('''INSERT INTO login_attempts (bucket, started_at, attempts) VALUES (?, ?, 1)
                    ON CONFLICT(bucket) DO UPDATE SET attempts = attempts + 1''', (bucket, now))
            return 0
    finally:
        conn.close()


def delete_user(user_id: int) -> bool:
    """Remove database records; retain profile files and reserve their former owner's name."""
    conn = get_conn()
    ensure_model_usage_schema(conn)
    conn.commit()
    conn.execute('BEGIN IMMEDIATE')
    conn.execute('INSERT OR IGNORE INTO retired_usernames (username) SELECT username FROM users WHERE id = ?', (user_id,))
    conn.execute("DELETE FROM jobs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM async_tasks WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM scraping_logs WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM model_calls WHERE user_id = ?", (user_id,))
    conn.execute("DELETE FROM user_model_quotas WHERE user_id = ?", (user_id,))
    cur = conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Public CRUD API
# ---------------------------------------------------------------------------
# Public CRUD API — all job access is scoped to a user
# ---------------------------------------------------------------------------

def load_jobs(user_id: int, is_one_off: bool = False) -> pd.DataFrame:
    """Return all (main or one-off) jobs of a user as a DataFrame."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND is_one_off=? ORDER BY date_scraped DESC",
        (user_id, int(is_one_off))
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([_merge_row(r) for r in rows])


def load_processed_jobs(user_id: int, is_one_off: bool = False) -> pd.DataFrame:
    """Return only AI-processed (processed=1) jobs of a user as a DataFrame."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND is_one_off=? AND processed=1 ORDER BY date_scraped DESC",
        (user_id, int(is_one_off))
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([_merge_row(r) for r in rows])


def load_unprocessed_jobs(user_id: int) -> list:
    """Return a user's jobs pending AI analysis or with previously failed analysis."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND (processed=0 OR (processed=1 AND match_score IS NULL AND match_rating IS NULL AND coalesce(json_extract(data, '$.analysis_state'), '') != 'complete')) AND is_one_off=0 AND "
        "coalesce(json_extract(data, '$.analysis_state'), '') != 'skipped' ORDER BY date_scraped DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [_merge_row(r) for r in rows]


def get_job_count(user_id: int) -> int:
    conn = get_conn()
    try:
        return conn.execute('SELECT COUNT(*) FROM jobs WHERE user_id = ?', (user_id,)).fetchone()[0]
    finally:
        conn.close()


def get_unprocessed_count(user_id: int) -> int:
    """Return the count of a user's unprocessed jobs."""
    conn = get_conn()
    count = conn.execute(
        "SELECT COUNT(*) FROM jobs WHERE user_id=? AND (processed=0 OR (processed=1 AND match_score IS NULL AND match_rating IS NULL AND coalesce(json_extract(data, '$.analysis_state'), '') != 'complete')) AND is_one_off=0 AND "
        "coalesce(json_extract(data, '$.analysis_state'), '') != 'skipped'",
        (user_id,)
    ).fetchone()[0]
    conn.close()
    return count


def load_all_jobs(user_id: int) -> pd.DataFrame:
    """Return all of a user's jobs (main + one-off) as a DataFrame."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? ORDER BY date_scraped DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([_merge_row(r) for r in rows])


def load_job_urls(user_id: int) -> set:
    """Return the set of a user's job_urls already in the DB (for fast dedup)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT job_url FROM jobs WHERE user_id=? AND job_url IS NOT NULL",
        (user_id,)
    ).fetchall()
    conn.close()
    return {r["job_url"] for r in rows}


def load_jobs_by_date(user_id: int, date: str) -> pd.DataFrame:
    """Return a user's jobs scraped on `date` (YYYY-MM-DD)."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM jobs WHERE user_id=? AND date_scraped=? ORDER BY match_score DESC",
        (user_id, date)
    ).fetchall()
    conn.close()
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame([_merge_row(r) for r in rows])


def load_distinct_scrape_dates(user_id: int) -> list:
    """Return a sorted-descending list of a user's distinct date_scraped values."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT DISTINCT date_scraped FROM jobs "
        "WHERE user_id=? AND date_scraped IS NOT NULL ORDER BY date_scraped DESC",
        (user_id,)
    ).fetchall()
    conn.close()
    return [r["date_scraped"] for r in rows]


def get_job_by_id(job_id: str, user_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM jobs WHERE id=? AND user_id=?",
        (job_id, user_id)
    ).fetchone()
    conn.close()
    return _merge_row(row) if row else None


def upsert_job(job: dict, user_id: Optional[int] = None, is_one_off: bool = False) -> None:
    if user_id is None:
        raise ValueError("upsert_job requires user_id (multi-user storage)")
    conn = get_conn()
    _upsert_job_conn(conn, job, is_one_off, user_id)
    conn.commit()
    conn.close()


def upsert_jobs_df(df: pd.DataFrame, user_id: Optional[int] = None, is_one_off: bool = False) -> None:
    """Bulk-upsert a DataFrame of jobs for a user."""
    if user_id is None:
        raise ValueError("upsert_jobs_df requires user_id (multi-user storage)")
    if df.empty:
        return
    df_clean = df.astype(object).where(pd.notna(df), None)
    conn = get_conn()
    for _, row in df_clean.iterrows():
        _upsert_job_conn(conn, row.to_dict(), is_one_off, user_id)
    conn.commit()
    conn.close()


def update_job_fields(job_id: str, user_id: int, **fields) -> bool:
    """
    Update specific fields of a user's job, keeping `data` blob in sync.
    Returns True if a row was found and updated.
    """
    conn = get_conn()
    row = conn.execute(
        "SELECT data FROM jobs WHERE id=? AND user_id=?",
        (job_id, user_id)
    ).fetchone()
    if not row:
        conn.close()
        return False

    blob = json.loads(row["data"] or "{}")
    blob.update(fields)
    if "german_level" in fields:
        blob["german_level"] = normalize_german_level(fields["german_level"])
        blob["requires_german"] = int(requires_german(fields["german_level"]))

    # Build SET clause for indexed columns that are being updated
    set_parts = {"data": json.dumps(blob, ensure_ascii=False, default=str)}
    for k, v in fields.items():
        if k in INDEXED_COLS:
            if k in ("requires_german", "applied"):
                set_parts[k] = _to_bool_int(v)
            elif k == "match_checks":
                set_parts[k] = json.dumps(v or [], ensure_ascii=False)
            elif k == "german_level":
                set_parts[k] = normalize_german_level(v)
                set_parts["requires_german"] = int(requires_german(v))
            else:
                set_parts[k] = v

    set_clause = ", ".join(f"{k}=:{k}" for k in set_parts)
    params = {**set_parts, "_id": job_id, "_uid": user_id}
    conn.execute(f"UPDATE jobs SET {set_clause} WHERE id=:_id AND user_id=:_uid", params)
    conn.commit()
    conn.close()
    return True


def delete_unreviewed_jobs(user_id: int) -> int:
    """Delete a user's jobs that are still 'new' or 'interested' — preserves pipeline entries."""
    conn = get_conn()
    cur = conn.execute(
        "DELETE FROM jobs WHERE user_id=? AND is_one_off=0 AND status NOT IN ('applied', 'interview', 'offer', 'rejected', 'not_interested')",
        (user_id,)
    )
    deleted = cur.rowcount
    conn.commit()
    conn.close()
    return deleted


def delete_job(job_id: str, user_id: int) -> bool:
    """Delete a single job of a user (any status). Returns True if a row was removed."""
    conn = get_conn()
    cur = conn.execute("DELETE FROM jobs WHERE id=? AND user_id=? AND is_one_off=0", (job_id, user_id))
    deleted = cur.rowcount > 0
    conn.commit()
    conn.close()
    return deleted


def delete_all_jobs(user_id: int) -> None:
    """Wipe ALL of a user's main jobs including tracked pipeline entries."""
    conn = get_conn()
    conn.execute("DELETE FROM jobs WHERE user_id=? AND is_one_off=0", (user_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Scraping logs
# ---------------------------------------------------------------------------

def get_logs(user_id: Optional[int] = None) -> list:
    """Return recent scraping log entries. Includes legacy (user_id NULL)
    entries plus the user's own; used by the live scraper console."""
    conn = get_conn()
    rows = conn.execute(
        "SELECT timestamp, message, level FROM scraping_logs "
        "WHERE user_id IS NULL OR user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, MAX_LOG_ROWS)
    ).fetchall()
    conn.close()
    return [{"timestamp": r["timestamp"], "message": r["message"], "level": r["level"]}
            for r in rows]


def add_log(message: str, level: str = "info", user_id: Optional[int] = None) -> None:
    conn = get_conn()
    conn.execute(
        "INSERT INTO scraping_logs (timestamp, message, level, user_id) VALUES (?, ?, ?, ?)",
        (datetime.now().isoformat(), message, level, user_id)
    )
    # Prune old rows
    conn.execute(
        "DELETE FROM scraping_logs WHERE id NOT IN "
        "(SELECT id FROM scraping_logs ORDER BY id DESC LIMIT ?)",
        (MAX_LOG_ROWS,)
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Background tasks (scrape / reprocess) — persisted for status polling across restarts
# ---------------------------------------------------------------------------

def async_task_create(
    task_id: str,
    kind: str,
    *,
    payload: Optional[dict] = None,
    total: Optional[int] = None,
    user_id: Optional[int] = None,
) -> None:
    now = time.time()
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO async_tasks (
            id, kind, status, created_at, updated_at, payload, result, logs,
            total, processed, failed, cancelled, user_id
        ) VALUES (?, ?, 'running', ?, ?, ?, NULL, '[]', ?, 0, 0, 0, ?)
        """,
        (
            task_id,
            kind,
            now,
            now,
            json.dumps(payload or {}, ensure_ascii=False),
            total,
            user_id,
        ),
    )
    conn.commit()
    conn.close()


class TaskCapacityError(Exception):
    """No background operation slot is available."""


def async_task_admit(task_id: str, kind: str, user_id: int, request_key: str,
                     payload: dict, total: Optional[int], *, max_total: int,
                     max_user: int) -> tuple[str, bool]:
    """Atomically reuse equivalent active work or reserve a persistent queue slot.

    The backend owner also serializes scheduler state around this transaction.
    This helper does not grant CLI/cron or multiple backend worker support.
    """
    conn = get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute("""SELECT id FROM async_tasks WHERE user_id = ? AND kind = ?
            AND request_key = ? AND status IN ('queued', 'running')
            ORDER BY created_at LIMIT 1""", (user_id, kind, request_key)).fetchone()
        if row:
            conn.commit()
            return row['id'], True
        counts = conn.execute("""SELECT COUNT(*) AS total,
            COALESCE(SUM(user_id = ?), 0) AS own FROM async_tasks
            WHERE status IN ('queued', 'running')""", (user_id,)).fetchone()
        if counts['total'] >= max_total or counts['own'] >= max_user:
            raise TaskCapacityError("Background queue is full for this account or server. Try again later.")
        now = time.time()
        conn.execute("""INSERT INTO async_tasks
            (id, kind, status, stage, request_key, created_at, updated_at, payload,
             logs, total, processed, failed, cancelled, user_id)
            VALUES (?, ?, 'queued', 'queued', ?, ?, ?, ?, '[]', ?, 0, 0, 0, ?)""",
            (task_id, kind, request_key, now, now, json.dumps(payload, ensure_ascii=False), total, user_id))
        conn.commit()
        return task_id, False
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def async_task_get(task_id: str, user_id: int) -> Optional[dict]:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM async_tasks WHERE id = ? AND user_id = ?",
                           (task_id, user_id)).fetchone()
        return _async_task_row_to_scrape_status(row) if row else None
    finally:
        conn.close()


def async_task_update(task_id: str, **fields: Any) -> None:
    """Update task columns. Pass result/logs/payload as dict/list — JSON-encoded."""
    if not fields:
        return
    allowed = {
        "status", "result", "logs", "total", "processed", "failed",
        "cancelled", "payload", "stage",
    }
    bad = set(fields) - allowed
    if bad:
        raise ValueError(f"Unsupported async_task fields: {bad}")
    if 'status' in fields and 'stage' not in fields:
        fields['stage'] = fields['status']
    sets = ["updated_at = ?"]
    vals: list = [time.time()]
    for k, v in fields.items():
        if k in ("result", "logs", "payload") and v is not None and not isinstance(v, str):
            sets.append(f"{k} = ?")
            vals.append(json.dumps(v, ensure_ascii=False))
        else:
            sets.append(f"{k} = ?")
            vals.append(v)
    vals.append(task_id)
    conn = get_conn()
    conn.execute(
        f"UPDATE async_tasks SET {', '.join(sets)} WHERE id = ?",
        vals,
    )
    conn.commit()
    conn.close()


def async_task_append_log(task_id: str, entry: dict) -> None:
    conn = get_conn()
    row = conn.execute("SELECT logs FROM async_tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        conn.close()
        return
    logs = json.loads(row["logs"] or "[]")
    logs.append(entry)
    conn.execute(
        "UPDATE async_tasks SET logs = ?, updated_at = ? WHERE id = ?",
        (json.dumps(logs, ensure_ascii=False), time.time(), task_id),
    )
    conn.commit()
    conn.close()


def _async_task_row_to_scrape_status(row: sqlite3.Row) -> dict:
    return {
        "status": row["status"],
        "stage": row["stage"] or row["status"],
        "logs": json.loads(row["logs"] or "[]"),
        "result": json.loads(row["result"]) if row["result"] else None,
        "created_at": row["created_at"],
        "total": row["total"],
        "processed": row["processed"] or 0,
        "failed": row["failed"] or 0,
        "cancelled": bool(row["cancelled"]),
    }


def _async_task_row_to_reprocess_status(row: sqlite3.Row) -> dict:
    return _async_task_row_to_scrape_status(row)


def async_task_get_scrape(task_id: str, user_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM async_tasks WHERE id = ? AND kind = 'scrape' AND user_id = ?", (task_id, user_id)
    ).fetchone()
    conn.close()
    return _async_task_row_to_scrape_status(row) if row else None


def async_task_get_reprocess(task_id: str, user_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM async_tasks WHERE id = ? AND kind = 'reprocess' AND user_id = ?", (task_id, user_id)
    ).fetchone()
    conn.close()
    return _async_task_row_to_reprocess_status(row) if row else None


def _async_task_row_to_batch_generate_status(row: sqlite3.Row) -> dict:
    return _async_task_row_to_scrape_status(row)


def async_task_get_batch_generate(task_id: str, user_id: int) -> Optional[dict]:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM async_tasks WHERE id = ? AND kind = 'batch_generate' AND user_id = ?", (task_id, user_id)
    ).fetchone()
    conn.close()
    return _async_task_row_to_batch_generate_status(row) if row else None


def async_task_cancel_running_reprocess(user_id: int) -> None:
    conn = get_conn()
    conn.execute(
        """
        UPDATE async_tasks SET cancelled = 1, updated_at = ?
        WHERE kind = 'reprocess' AND status = 'running' AND user_id = ?
        """,
        (time.time(), user_id),
    )
    conn.commit()
    conn.close()


def async_task_get_latest_running_reprocess(user_id: int) -> Optional[tuple[str, dict]]:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT * FROM async_tasks
        WHERE kind = 'reprocess' AND status IN ('queued', 'running') AND user_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return row["id"], _async_task_row_to_reprocess_status(row)


def async_task_get_latest_running_scrape(user_id: int) -> Optional[tuple[str, dict]]:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT * FROM async_tasks
        WHERE kind = 'scrape' AND status IN ('queued', 'running') AND user_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return row["id"], _async_task_row_to_scrape_status(row)


def async_task_get_latest_running_batch_generate(user_id: int) -> Optional[tuple[str, dict]]:
    conn = get_conn()
    row = conn.execute(
        """
        SELECT * FROM async_tasks
        WHERE kind = 'batch_generate' AND status IN ('queued', 'running') AND user_id = ?
        ORDER BY created_at DESC LIMIT 1
        """,
        (user_id,),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return row["id"], _async_task_row_to_batch_generate_status(row)


def async_task_cancel_running_batch_generate(user_id: int) -> None:
    conn = get_conn()
    conn.execute(
        """
        UPDATE async_tasks SET cancelled = 1, updated_at = ?
        WHERE kind = 'batch_generate' AND status = 'running' AND user_id = ?
        """,
        (time.time(), user_id),
    )
    conn.commit()
    conn.close()


def async_task_prune_completed(older_than_sec: float = 3600) -> int:
    """Remove finished scrape / reprocess / batch_generate tasks older than the cutoff."""
    cutoff = time.time() - older_than_sec
    conn = get_conn()
    cur = conn.execute(
        """
        DELETE FROM async_tasks
        WHERE updated_at < ? AND status IN ('completed', 'failed', 'cancelled', 'interrupted')
        """,
        (cutoff,),
    )
    n = cur.rowcount
    conn.commit()
    conn.close()
    return n


def async_task_recover_interrupted() -> None:
    """Owner-only startup: interrupt unfinished work; never silently rerun it."""
    msg = json.dumps(
        {"success": False, "message": "Task interrupted by server shutdown/restart. Retry explicitly; saved work may already exist."},
        ensure_ascii=False,
    )
    conn = get_conn()
    conn.execute(
        """
        UPDATE async_tasks SET status = 'interrupted', stage = 'interrupted', result = ?, updated_at = ?
        WHERE status IN ('queued', 'running')
        """,
        (msg, time.time()),
    )
    conn.commit()
    conn.close()
