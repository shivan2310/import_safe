"""Result models for the TinyFish connector.

All page text is untrusted data (docs/prd-backend.md B6). Text is stripped of control characters, capped in
length and, for ``raw_text``, wrapped in explicit markers so it can never be mistaken for instructions.
Nothing here is ever executed or evaluated.
"""
import json
import re
from datetime import datetime
from typing import Any, Dict, Optional, Sequence, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_RAW_TEXT = 20000
MAX_EXCERPT = 2000  # matches the stored-excerpt cap in decisions.md section 7
MAX_VALUE = 2000
MAX_KEY = 100
MAX_LIST_ITEMS = 50

UNTRUSTED_START = "<<<UNTRUSTED_PAGE_TEXT_START>>>"
UNTRUSTED_END = "<<<UNTRUSTED_PAGE_TEXT_END>>>"

# Control characters (except tab and newline), zero-width and bidi override characters.
_UNSAFE_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f​-‏‪-‮⁦-⁩﻿]")
_MISSING_MARKERS = {"", "n/a", "na", "null", "none", "unknown"}


def clean_text(text: Any, max_len: int) -> str:
    """Strip unsafe characters and surrounding whitespace, then cap the length. Non-strings give ''."""
    if not isinstance(text, str):
        return ""
    return _UNSAFE_RE.sub("", text).strip()[:max_len]


def delimit_untrusted(text: Any, max_len: int = MAX_RAW_TEXT) -> str:
    """Clean page text, remove any copy of the delimiters inside it, and wrap it in the delimiters."""
    body = clean_text(text, max_len)
    body = body.replace(UNTRUSTED_START, "").replace(UNTRUSTED_END, "")
    return f"{UNTRUSTED_START}\n{body}\n{UNTRUSTED_END}"


def is_missing(value: Any) -> bool:
    """True for a value that means 'not shown': None, empty, or an N/A marker."""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() in _MISSING_MARKERS
    if isinstance(value, (list, dict)):
        return len(value) == 0
    return False


def _clean_value(value: Any, depth: int = 0) -> Any:
    """Reduce a value to plain str, int, bool, list or dict[str, ...]. Anything else becomes None."""
    if value is None or isinstance(value, bool) or isinstance(value, int):
        return value
    if isinstance(value, float):
        return str(value)  # never keep floats; money and numbers stay textual
    if isinstance(value, str):
        return clean_text(value, MAX_VALUE)
    if isinstance(value, (list, tuple)) and depth < 2:
        items = [_clean_value(item, depth + 1) for item in list(value)[:MAX_LIST_ITEMS]]
        return [item for item in items if not is_missing(item)]
    if isinstance(value, dict) and depth < 2:
        cleaned = {}
        for key, item in list(value.items())[:MAX_LIST_ITEMS]:
            name = clean_text(key, MAX_KEY) if isinstance(key, str) else ""
            item = _clean_value(item, depth + 1)
            if name and not is_missing(item):
                cleaned[name] = item
        return cleaned
    return None


def extract_fields(raw: Any, allowed_keys: Sequence[str]) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Pull the whitelisted keys out of an agent result.

    Each key may hold ``{"value": ..., "excerpt": ...}`` or a bare value. Keys outside ``allowed_keys`` are
    dropped. Missing values and N/A markers are left out, and an excerpt is kept only for a field that is kept.
    """
    fields: Dict[str, Any] = {}
    excerpts: Dict[str, str] = {}
    if not isinstance(raw, dict):
        return fields, excerpts
    for key in allowed_keys:
        entry = raw.get(key)
        excerpt = None
        if isinstance(entry, dict) and "value" in entry:
            excerpt = entry.get("excerpt")
            entry = entry.get("value")
        value = _clean_value(entry)
        if is_missing(value):
            continue
        fields[key] = value
        text = clean_text(excerpt, MAX_EXCERPT)
        if not is_missing(text):
            excerpts[key] = text
    return fields, excerpts


def raw_text_from_result(raw: Any) -> str:
    """Serialise an agent result for storage as delimited, untrusted text."""
    try:
        text = json.dumps(raw, ensure_ascii=False, default=str)
    except (TypeError, ValueError):
        text = ""
    return delimit_untrusted(text)


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_text: str = ""
    fields: Dict[str, Any] = Field(default_factory=dict)
    source_url: str
    retrieved_at: datetime
    excerpt_map: Dict[str, str] = Field(default_factory=dict)
    run_id: Optional[str] = None
    steps_used: int = 0
    status: str
    failed: bool
    is_fixture: bool = False

    @field_validator("retrieved_at")
    @classmethod
    def _check_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value

    @field_validator("fields")
    @classmethod
    def _clean_fields(cls, value: Dict[str, Any]) -> Dict[str, Any]:
        cleaned = {}
        for key, item in value.items():
            item = _clean_value(item)
            if not is_missing(item):
                cleaned[clean_text(key, MAX_KEY)] = item
        return cleaned

    @field_validator("excerpt_map")
    @classmethod
    def _clean_excerpts(cls, value: Dict[str, str]) -> Dict[str, str]:
        cleaned = {}
        for key, item in value.items():
            text = clean_text(item, MAX_EXCERPT)
            if text:
                cleaned[clean_text(key, MAX_KEY)] = text
        return cleaned


class RegistryResult(ExtractionResult):
    record_found: bool = False
