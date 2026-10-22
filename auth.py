"""auth.py — password hashing and signed session cookies (stdlib only).

Passwords use PBKDF2-HMAC-SHA256 with a random salt. Sessions are stateless:
an HMAC-signed `{user_id}.{expires}` token stored in an HttpOnly cookie.
The signing secret lives in `.session_secret` (gitignored, auto-generated).
"""

import hashlib
import hmac
import os
import secrets
import time
from user_assets import DATA_DIR

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SECRET_FILE = os.path.join(DATA_DIR, ".session_secret")

SESSION_COOKIE_NAME = "gj_session"
SESSION_TTL_SECONDS = 30 * 24 * 3600  # 30 days
_PBKDF2_ITERATIONS = 200_000

_secret_cache: bytes | None = None


def _load_secret() -> bytes:
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    if os.path.exists(SECRET_FILE):
        with open(SECRET_FILE, "rb") as f:
            secret = f.read().strip()
        if secret:
            _secret_cache = secret
            return _secret_cache
    secret = secrets.token_hex(32).encode()
    with open(SECRET_FILE, "wb") as f:
        f.write(secret)
    os.chmod(SECRET_FILE, 0o600)
    _secret_cache = secret
    return _secret_cache


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), _PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${_PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not password:
        return False
    try:
        _, iterations, salt, expected = stored.split("$")
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def create_session_token(user_id: int) -> str:
    expires = int(time.time()) + SESSION_TTL_SECONDS
    payload = f"{user_id}.{expires}"
    sig = hmac.new(_load_secret(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str | None) -> int | None:
    """Return the user_id encoded in a valid, unexpired token — else None."""
    if not token:
        return None
    try:
        user_id_part, expires_part, sig = token.split(".")
        payload = f"{user_id_part}.{expires_part}"
        expected = hmac.new(_load_secret(), payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        if int(expires_part) < time.time():
            return None
        return int(user_id_part)
    except (ValueError, TypeError):
        return None
