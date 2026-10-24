"""Pure text normalisers for the verification engine.

See docs/decisions.md section 6. Scope: Step 3a — normalisation only. No
field comparison, overall result or follow-up questions live here.

Pure functions only: no I/O, no clock, no randomness, no eval/exec.
"""
import re
import unicodedata
from fnmatch import translate as _fnmatch_translate
from typing import List, Optional

_PUNCT_RE = re.compile(r"[^a-z0-9\s]")
# Model normalisation keeps * and ? — they are wildcard syntax, not punctuation.
_MODEL_PUNCT_RE = re.compile(r"[^a-z0-9\s*?]")
_WHITESPACE_RE = re.compile(r"\s+")
_REG_STRIP_RE = re.compile(r"[\s\-/]")
_TRAILING_X_RE = re.compile(r"[xX]+$")


def normalize_registration(raw: Optional[str]) -> Optional[str]:
    """Uppercase, strip spaces/hyphens/slashes. None when empty or None."""
    if raw is None:
        return None
    cleaned = _REG_STRIP_RE.sub("", raw).upper()
    return cleaned if cleaned else None


def _ascii_fold(raw: str) -> str:
    nfkd = unicodedata.normalize("NFKD", raw)
    return nfkd.encode("ascii", "ignore").decode("ascii")


def _tokenize(raw: str, punct_re: "re.Pattern[str]" = _PUNCT_RE) -> List[str]:
    folded = _ascii_fold(raw).lower()
    no_punct = punct_re.sub(" ", folded)
    collapsed = _WHITESPACE_RE.sub(" ", no_punct).strip()
    return collapsed.split(" ") if collapsed else []


def normalize_name(raw: Optional[str], legal_suffixes: List[str]) -> Optional[str]:
    """NFKD/ASCII/lowercase/depunctuate, drop legal suffixes, sort tokens.

    Returns None when the result is empty (including a name that is only a
    legal suffix).
    """
    if raw is None:
        return None
    suffixes = {s.lower() for s in legal_suffixes}
    tokens = [t for t in _tokenize(raw) if t not in suffixes]
    if not tokens:
        return None
    tokens.sort()
    return " ".join(tokens)


def normalize_model(raw: Optional[str]) -> Optional[str]:
    """Same pipeline as normalize_name, but tokens keep their original order.

    Model normalisation has no legal-suffix list to strip, and keeps * and ?
    (wildcard syntax) rather than treating them as punctuation to remove.
    """
    if raw is None:
        return None
    tokens = _tokenize(raw, _MODEL_PUNCT_RE)
    if not tokens:
        return None
    return " ".join(tokens)


def _token_to_regex(token: str) -> str:
    """Build a case-insensitive fullmatch regex for one normalised token.

    * and ? use fnmatch semantics. A trailing run of x/X (already lowercased
    by normalize_model) becomes one \\d per character. Never uses eval/exec.
    """
    trailing = _TRAILING_X_RE.search(token)
    if trailing and "*" not in token and "?" not in token:
        prefix = token[: trailing.start()]
        digit_count = len(trailing.group())
        return re.escape(prefix) + r"\d" * digit_count
    # fnmatch.translate produces a regex ending in \Z; drop anchors we add ourselves.
    pattern = _fnmatch_translate(token)
    return pattern


def _is_wildcard_token(token: str) -> bool:
    if "*" in token or "?" in token:
        return True
    return bool(_TRAILING_X_RE.search(token))


def model_matches_scope(claim_model: Optional[str], scope: List[str]) -> Optional[bool]:
    """Check claim_model against a list of exact/wildcard scope entries.

    None claim -> None (unknown). Empty scope -> None (cannot determine).
    Otherwise True on first match, False if no entry matches. Scope entries
    that normalise to empty are skipped.
    """
    if claim_model is None:
        return None
    if not scope:
        return None

    claim_norm = normalize_model(claim_model)
    if claim_norm is None:
        return None
    claim_tokens = claim_norm.split(" ")

    for entry in scope:
        entry_norm = normalize_model(entry)
        if not entry_norm:
            continue
        entry_tokens = entry_norm.split(" ")
        if len(claim_tokens) != len(entry_tokens):
            continue
        if any(_is_wildcard_token(et) for et in entry_tokens):
            # Match token-by-token: an exact token falls back to a literal
            # regex via fnmatch.translate, so this also covers mixed entries.
            if all(
                re.fullmatch(_token_to_regex(et), ct, re.IGNORECASE)
                for et, ct in zip(entry_tokens, claim_tokens)
            ):
                return True
        else:
            if entry_norm == claim_norm:
                return True
    return False
