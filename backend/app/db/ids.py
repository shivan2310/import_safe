"""ULID helpers. Every ID stored by app/db is a ULID (docs/decisions.md section 10)."""
import re
from typing import Any

from ulid import ULID

# 26 Crockford base32 characters; the first is 0-7 so the 48-bit timestamp does not overflow.
_ULID_RE = re.compile(r"^[0-7][0-9A-HJKMNP-TV-Z]{25}$")


class InvalidIdError(ValueError):
    """An ID is not a valid ULID."""


def new_ulid() -> str:
    return str(ULID())


def is_valid_ulid(value: Any) -> bool:
    return isinstance(value, str) and _ULID_RE.match(value) is not None


def require_ulid(value: Any, what: str = "id") -> str:
    if not is_valid_ulid(value):
        raise InvalidIdError(f"{what} must be a ULID (26 characters, Crockford base32)")
    return value
