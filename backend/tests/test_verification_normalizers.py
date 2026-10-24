"""Tests for Step 3a: verification config and text normalisers.

Scope: normalisation only. No field comparison, overall result or
follow-up questions are tested here (they don't exist yet).
"""
import ast
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.decision.verification_config import (
    VerificationConfig,
    load_verification_config,
    parse_verification_config,
)
from app.decision.verification_normalizers import (
    model_matches_scope,
    normalize_model,
    normalize_name,
    normalize_registration,
)

LEGAL_SUFFIXES = ["co", "ltd", "limited", "llc", "inc", "corp", "corporation",
                   "pvt", "private", "gmbh", "sa", "plc", "company"]


# ---------------------------------------------------------------------------
# normalize_registration
# ---------------------------------------------------------------------------

def test_registration_none_returns_none():
    assert normalize_registration(None) is None


def test_registration_empty_returns_none():
    assert normalize_registration("") is None


def test_registration_whitespace_only_returns_none():
    assert normalize_registration("   ") is None


def test_registration_hyphen_and_space_variants_equal():
    a = normalize_registration("R-41234567")
    b = normalize_registration("r41234567")
    c = normalize_registration("R 41 234 567")
    assert a == b == c == "R41234567"


def test_registration_strips_slashes():
    assert normalize_registration("R/41234567") == "R41234567"


def test_registration_mixed_punctuation():
    assert normalize_registration("R / 41-234 567") == "R41234567"


def test_registration_uppercases():
    assert normalize_registration("abc123") == "ABC123"


def test_registration_different_numbers_not_equal():
    assert normalize_registration("R-1") != normalize_registration("R-2")


# ---------------------------------------------------------------------------
# normalize_name
# ---------------------------------------------------------------------------

def test_name_none_returns_none():
    assert normalize_name(None, LEGAL_SUFFIXES) is None


def test_name_unicode_cafe():
    assert normalize_name("café", []) == "cafe"


def test_name_unicode_naive():
    assert normalize_name("naïve", []) == "naive"


def test_name_legal_suffix_removed_whole_word():
    assert normalize_name("Acme Ltd", LEGAL_SUFFIXES) == "acme"


def test_name_suffix_not_removed_as_substring():
    # "limited" is a legal suffix as a whole word, but a word that merely
    # contains similar letters, e.g. "factory", must keep its own letters
    # intact ("fact" only appears via whole-token removal, never substring).
    result = normalize_name("Acme Factory", LEGAL_SUFFIXES)
    assert "factory" in result.split(" ")


def test_name_suffix_as_whole_token_is_removed_not_partial():
    # "limited" used as a whole token is removed; it must not partially
    # strip letters from an unrelated word like "unlimited".
    result = normalize_name("Acme Unlimited", LEGAL_SUFFIXES)
    assert result == "acme unlimited"


def test_name_punctuation_removed():
    assert normalize_name("Acme, Inc.", LEGAL_SUFFIXES) == "acme"


def test_name_tokens_sorted():
    a = normalize_name("Factory Acme", [])
    b = normalize_name("Acme Factory", [])
    assert a == b == "acme factory"


def test_name_empty_after_normalisation_returns_none():
    assert normalize_name("   ", LEGAL_SUFFIXES) is None


def test_name_only_suffix_returns_none():
    assert normalize_name("Ltd", LEGAL_SUFFIXES) is None


def test_name_only_suffix_multi_word_returns_none():
    assert normalize_name("Co Ltd", LEGAL_SUFFIXES) is None


def test_name_extra_whitespace_collapsed():
    assert normalize_name("Acme    Factory", []) == "acme factory"


def test_name_case_insensitive():
    assert normalize_name("ACME", []) == normalize_name("acme", []) == "acme"


# ---------------------------------------------------------------------------
# normalize_model
# ---------------------------------------------------------------------------

def test_model_none_returns_none():
    assert normalize_model(None) is None


def test_model_tokens_not_sorted():
    a = normalize_model("BT-100")
    b = normalize_model("100-BT")
    assert a != b
    assert a == "bt 100"
    assert b == "100 bt"


def test_model_unicode():
    assert normalize_model("café-100") == "cafe 100"


def test_model_punctuation_removed_but_wildcards_kept():
    assert normalize_model("BT-1*") == "bt 1*"
    assert normalize_model("BT-1?") == "bt 1?"


def test_model_empty_after_normalisation_returns_none():
    assert normalize_model("---") is None


def test_model_extra_whitespace_collapsed():
    assert normalize_model("BT   100") == "bt 100"


def test_model_case_insensitive_normalisation():
    assert normalize_model("bt-100") == normalize_model("BT-100") == "bt 100"


# ---------------------------------------------------------------------------
# model_matches_scope
# ---------------------------------------------------------------------------

def test_scope_claim_none_returns_none():
    assert model_matches_scope(None, ["BT-100"]) is None


def test_scope_empty_scope_returns_none():
    assert model_matches_scope("BT-100", []) is None


def test_scope_exact_match():
    assert model_matches_scope("BT-100", ["BT-100"]) is True


def test_scope_exact_no_match():
    assert model_matches_scope("BT-200", ["BT-100"]) is False


def test_scope_star_wildcard_matches():
    assert model_matches_scope("BT-100", ["BT-1*"]) is True
    assert model_matches_scope("BT-199", ["BT-1*"]) is True


def test_scope_star_wildcard_no_match():
    assert model_matches_scope("BT-200", ["BT-1*"]) is False


def test_scope_question_wildcard_matches_exactly_one_char():
    assert model_matches_scope("BT-10", ["BT-1?"]) is True
    assert model_matches_scope("BT-19", ["BT-1?"]) is True


def test_scope_question_wildcard_rejects_two_chars():
    assert model_matches_scope("BT-100", ["BT-1?"]) is False


def test_scope_trailing_x_matches_single_digit():
    assert model_matches_scope("BT-10", ["BT-1x"]) is True
    assert model_matches_scope("BT-19", ["BT-1x"]) is True


def test_scope_trailing_x_rejects_three_digits():
    assert model_matches_scope("BT-100", ["BT-1x"]) is False


def test_scope_trailing_xx_matches_two_digits():
    assert model_matches_scope("BT-100", ["BT-1xx"]) is True
    assert model_matches_scope("BT-199", ["BT-1xx"]) is True


def test_scope_trailing_xx_rejects_four_digits():
    assert model_matches_scope("BT-1000", ["BT-1xx"]) is False


def test_scope_trailing_xx_rejects_different_prefix():
    assert model_matches_scope("BT-200", ["BT-1xx"]) is False


def test_scope_trailing_uppercase_X():
    assert model_matches_scope("BT-10", ["BT-1X"]) is True
    assert model_matches_scope("BT-100", ["BT-1X"]) is False


def test_scope_case_insensitive_matching():
    assert model_matches_scope("bt-100", ["BT-100"]) is True
    assert model_matches_scope("BT-100", ["bt-1xx"]) is True


def test_scope_mixed_exact_and_wildcard_entries():
    scope = ["BT-50", "BT-1xx", "CT-999"]
    assert model_matches_scope("BT-150", scope) is True
    assert model_matches_scope("BT-50", scope) is True
    assert model_matches_scope("CT-999", scope) is True
    assert model_matches_scope("ZZ-1", scope) is False


def test_scope_punctuation_only_entry_is_skipped():
    # "---" normalises to empty and must not match (or error on) anything.
    assert model_matches_scope("BT-100", ["---", "BT-100"]) is True
    assert model_matches_scope("BT-999", ["---"]) is False


def test_scope_no_match_in_nonempty_scope_returns_false():
    assert model_matches_scope("ZZ-1", ["BT-100", "BT-200"]) is False


def test_scope_claim_empty_after_normalisation_returns_none():
    # An all-punctuation claim normalises to None (unknown), not False.
    assert model_matches_scope("---", ["BT-100"]) is None


# ---------------------------------------------------------------------------
# AST check: no eval/exec/os/pathlib/socket/requests/httpx/time/datetime/random
# ---------------------------------------------------------------------------

_FORBIDDEN_NAMES = {
    "eval", "exec", "os", "pathlib", "socket", "requests", "httpx",
    "time", "datetime", "random",
}


def test_normalizers_module_has_no_forbidden_imports_or_calls():
    module_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "decision" / "verification_normalizers.py"
    )
    tree = ast.parse(module_path.read_text(encoding="utf-8"))

    imported_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_names.add(alias.asname or alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_names.add(node.module.split(".")[0])
            for alias in node.names:
                imported_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            imported_names.add(node.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            imported_names.add(node.func.id)

    forbidden_found = imported_names & _FORBIDDEN_NAMES
    assert not forbidden_found, f"forbidden names used: {forbidden_found}"


# ---------------------------------------------------------------------------
# Config: validation
# ---------------------------------------------------------------------------

def _base_config_data():
    return {
        "fuzzy_threshold": 0.85,
        "legal_suffixes": LEGAL_SUFFIXES,
        "inactive_statuses": ["cancelled", "suspended", "expired", "withdrawn", "revoked"],
        "required_fields": ["registration_no", "manufacturer", "model_scope", "validity"],
        "optional_fields": ["factory_location", "category", "brand"],
    }


def test_config_loads_from_yaml_with_defaults_present():
    cfg = load_verification_config()
    assert cfg.fuzzy_threshold == 0.85
    assert "ltd" in cfg.legal_suffixes
    assert "cancelled" in cfg.inactive_statuses
    assert set(cfg.required_fields) == {"registration_no", "manufacturer", "model_scope", "validity"}
    assert set(cfg.optional_fields) == {"factory_location", "category", "brand"}


def test_config_threshold_zero_rejected():
    data = _base_config_data()
    data["fuzzy_threshold"] = 0.0
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_threshold_one_rejected():
    data = _base_config_data()
    data["fuzzy_threshold"] = 1.0
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_threshold_valid_accepted():
    data = _base_config_data()
    data["fuzzy_threshold"] = 0.5
    cfg = parse_verification_config(data)
    assert cfg.fuzzy_threshold == 0.5


def test_config_non_lowercase_suffix_rejected():
    data = _base_config_data()
    data["legal_suffixes"] = ["Ltd"]
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_non_lowercase_status_rejected():
    data = _base_config_data()
    data["inactive_statuses"] = ["Cancelled"]
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_unknown_required_field_rejected():
    data = _base_config_data()
    data["required_fields"] = ["not_a_real_field"]
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_unknown_optional_field_rejected():
    data = _base_config_data()
    data["optional_fields"] = ["not_a_real_field"]
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_overlap_between_required_and_optional_rejected():
    data = _base_config_data()
    data["optional_fields"] = ["registration_no"]
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_empty_suffix_string_rejected():
    data = _base_config_data()
    data["legal_suffixes"] = [""]
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_extra_unknown_top_level_field_rejected():
    data = _base_config_data()
    data["something_else"] = 1
    with pytest.raises(ValidationError):
        parse_verification_config(data)
