"""Password hashing and revocable sessions. Only session-token hashes are stored."""

import hashlib
import hmac
import re
import secrets
import time

SESSION_COOKIE_NAME = "gj_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days
_PBKDF2_ITERATIONS = 600_000


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        return False
    try:
        algorithm, iterations, salt, expected = stored.split("$")
        if algorithm != 'pbkdf2_sha256' or not 1 <= int(iterations) <= 2_000_000:
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError, OverflowError):
        return False


def password_needs_upgrade(stored: str) -> bool:
    return int(stored.split('$')[1]) < _PBKDF2_ITERATIONS


def create_session_token(user_id: int, credential_hash=None) -> str:
    from jobweaver import db
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    if not db.create_session(user_id, hashlib.sha256(token.encode()).hexdigest(),
                             now + SESSION_TTL_SECONDS, now, credential_hash):
        raise ValueError('Account credentials changed. Sign in again.')
    return token


def verify_session_token(token: str | None) -> int | None:
    if not isinstance(token, str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}', token):
        return None
    from jobweaver import db
    return db.session_user(hashlib.sha256(token.encode()).hexdigest(), int(time.time()))


def revoke_session_token(token: str | None) -> None:
    if isinstance(token, str):
        from jobweaver import db
        db.revoke_session(hashlib.sha256(token.encode()).hexdigest())


def reserve_login_attempt(username: str, address: str, now: int) -> int:
    from jobweaver import db
    def bucket(value):
        return hashlib.sha256(value.encode()).hexdigest()
    return db.reserve_login_attempt({bucket('peer:' + address): 30,
                                     bucket('user-peer:' + username.strip().lower() + '\0' + address): 5}, now)
