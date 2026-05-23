from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import datetime, timedelta, timezone

SESSION_COOKIE = "fredcore_session"
SESSION_DAYS = 30


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260000)
    return f"pbkdf2:sha256:260000:{salt}:{key.hex()}"


def verify_password(stored_hash: str, password: str) -> bool:
    try:
        _, algo, iters, salt, stored_key = stored_hash.split(":")
        key = hashlib.pbkdf2_hmac(algo, password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(key.hex(), stored_key)
    except Exception:
        return False


def generate_session_token() -> str:
    return secrets.token_hex(32)


def session_expires_at() -> str:
    dt = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    return dt.replace(microsecond=0).isoformat()


def get_session_cookie(environ: dict) -> str:
    for part in environ.get("HTTP_COOKIE", "").split(";"):
        name, _, value = part.strip().partition("=")
        if name.strip() == SESSION_COOKIE:
            return value.strip()
    return ""


def make_session_cookie(token: str) -> str:
    return f"{SESSION_COOKIE}={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_DAYS * 86400}"


def clear_session_cookie() -> str:
    return f"{SESSION_COOKIE}=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
