"""Anonymous session IDs in a signed cookie. See docs/decisions.md section 10.

The cookie value is `<ULID>.<hex HMAC-SHA256 of the ULID>`, keyed with SECRET_KEY. A missing,
tampered or malformed cookie is replaced with a new session ID. SECRET_KEY has no default.
"""
import hashlib
import hmac
import os
from typing import Any, Dict, Optional, Tuple

from app.db.ids import is_valid_ulid, new_ulid

COOKIE_NAME = "importsafe_session"
MIN_SECRET_LENGTH = 32
MAX_COOKIE_LENGTH = 128
_SIG_HEX_LENGTH = 64  # SHA-256


class SessionConfigError(RuntimeError):
    """SECRET_KEY is missing or too short."""


def _secret_bytes(secret: Optional[str]) -> bytes:
    value = secret if secret is not None else os.environ.get("SECRET_KEY", "")
    if len(value) < MIN_SECRET_LENGTH:
        raise SessionConfigError(f"SECRET_KEY must be set and at least {MIN_SECRET_LENGTH} characters long")
    return value.encode("utf-8")


def _signature(session_id: str, secret: bytes) -> str:
    return hmac.new(secret, session_id.encode("ascii"), hashlib.sha256).hexdigest()


def sign_session(session_id: str, secret: Optional[str] = None) -> str:
    if not is_valid_ulid(session_id):
        raise ValueError("session id must be a ULID")
    return f"{session_id}.{_signature(session_id, _secret_bytes(secret))}"


def verify_session(cookie: Optional[str], secret: Optional[str] = None) -> Optional[str]:
    """Return the session ID if the cookie is validly signed, else None."""
    key = _secret_bytes(secret)  # a configuration error is raised even for a missing cookie
    if not isinstance(cookie, str) or not cookie or len(cookie) > MAX_COOKIE_LENGTH:
        return None
    session_id, dot, signature = cookie.partition(".")
    if not dot or not is_valid_ulid(session_id) or len(signature) != _SIG_HEX_LENGTH:
        return None
    expected = _signature(session_id, key)
    try:
        ok = hmac.compare_digest(signature.encode("ascii"), expected.encode("ascii"))
    except UnicodeEncodeError:
        return None
    return session_id if ok else None


def resolve_session(cookie: Optional[str], secret: Optional[str] = None) -> Tuple[str, bool]:
    """Return (session_id, is_new). Generates a new ULID when the cookie is missing or invalid."""
    existing = verify_session(cookie, secret)
    if existing is not None:
        return existing, False
    return new_ulid(), True


def cookie_attributes(max_age_s: int, *, secure: bool = True) -> Dict[str, Any]:
    """Attributes for Set-Cookie: not readable by scripts, not sent cross-site."""
    if max_age_s <= 0:
        raise ValueError("max_age_s must be positive")
    return {"max_age": max_age_s, "httponly": True, "samesite": "lax", "secure": secure, "path": "/"}
