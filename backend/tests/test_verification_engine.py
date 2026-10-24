"""Tests for Step 3: the verification engine (field comparison, overall
result, seller request list).

Scope: engine logic only. Config and normaliser-level tests already live in
test_verification_normalizers.py and are not duplicated here except for the
engine-specific AST and config checks the brief calls for.
"""
import ast
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.decision.enums import FieldMatch, IdentityResult
from app.decision.verification_config import load_verification_config, parse_verification_config
from app.decision.verification_engine import CertClaim, CertRecord, verify_certification

from tests.fixtures.verification_cases import (
    ALL_CASES,
    CANCELLED_STATUS,
    CLAIM_MISSING_REGISTRATION_NO,
    EXPIRED_RECORD,
    FULL_MATCH,
    LEGAL_SUFFIX_DIFFERENCE,
    MANUFACTURER_MISMATCH,
    MANUFACTURER_PARTIAL,
    MODEL_WILDCARD_MATCH,
    MODEL_WILDCARD_MISS,
    NOT_YET_VALID,
    OPTIONAL_FIELD_MISMATCH_ONLY,
    RECORD_NONE,
    REGISTRATION_CASE_HYPHEN_DIFFERENCE,
    SAME_INPUTS_SAME_OUTPUT,
    UNRELIABLE_RECORD_NO_EXCERPT,
    UNRELIABLE_RECORD_WRONG_SOURCE_TYPE,
    WRONG_MODEL,
    _matching_claim,
    _reliable_record,
)

CONFIG = load_verification_config()


def _result_for(case):
    return verify_certification(case.claim, case.record, case.as_of, CONFIG)


# ---------------------------------------------------------------------------
# Named fixture cases (deliverable 6), run through the engine (deliverable 7)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case", ALL_CASES, ids=[c.name for c in ALL_CASES])
def test_fixture_case_matches_expected_overall_and_conflicts(case):
    result = _result_for(case)
    assert result.overall == case.expected_overall, (
        f"{case.name}: expected {case.expected_overall}, got {result.overall}"
    )
    assert result.conflicts == case.expected_conflicts, (
        f"{case.name}: expected conflicts {case.expected_conflicts}, got {result.conflicts}"
    )


def test_full_match_is_verified():
    result = _result_for(FULL_MATCH)
    assert result.overall == IdentityResult.verified
    assert result.record_reliable is True


def test_legal_suffix_and_case_difference_is_match_not_mismatch():
    result = _result_for(LEGAL_SUFFIX_DIFFERENCE)
    manufacturer = next(f for f in result.field_results if f.field == "manufacturer")
    assert manufacturer.result == FieldMatch.match
    assert result.overall == IdentityResult.verified


def test_manufacturer_above_fuzzy_threshold_is_partial_and_overall_unverified():
    result = _result_for(MANUFACTURER_PARTIAL)
    manufacturer = next(f for f in result.field_results if f.field == "manufacturer")
    assert manufacturer.result == FieldMatch.partial
    assert result.overall == IdentityResult.unverified


def test_manufacturer_below_threshold_reliable_record_is_contradiction():
    result = _result_for(MANUFACTURER_MISMATCH)
    manufacturer = next(f for f in result.field_results if f.field == "manufacturer")
    assert manufacturer.result == FieldMatch.mismatch
    assert result.overall == IdentityResult.contradiction_detected
    assert "manufacturer" in result.conflicts


def test_model_not_in_scope_reliable_record_is_contradiction():
    result = _result_for(WRONG_MODEL)
    assert result.overall == IdentityResult.contradiction_detected
    assert "model_scope" in result.conflicts


def test_model_wildcard_bt1xx_matches_bt150():
    result = _result_for(MODEL_WILDCARD_MATCH)
    assert result.overall == IdentityResult.verified


def test_model_wildcard_bt1xx_does_not_match_bt200():
    result = _result_for(MODEL_WILDCARD_MISS)
    assert result.overall == IdentityResult.contradiction_detected


def test_model_wildcard_bt1xx_does_not_match_bt1000():
    claim = _matching_claim(model="BT-1000")
    record = _reliable_record(model_scope=["BT-1xx"])
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    assert result.overall == IdentityResult.contradiction_detected
    assert "model_scope" in result.conflicts


def test_expired_as_of_is_contradiction():
    result = _result_for(EXPIRED_RECORD)
    assert result.overall == IdentityResult.contradiction_detected
    assert "validity" in result.conflicts


def test_not_yet_valid_is_contradiction():
    result = _result_for(NOT_YET_VALID)
    assert result.overall == IdentityResult.contradiction_detected
    assert "validity" in result.conflicts


def test_status_cancelled_is_contradiction():
    result = _result_for(CANCELLED_STATUS)
    assert result.overall == IdentityResult.contradiction_detected
    assert "validity" in result.conflicts


def test_record_none_is_unverified():
    result = _result_for(RECORD_NONE)
    assert result.overall == IdentityResult.unverified
    assert result.record_reliable is False


def test_unreliable_record_no_excerpt_never_yields_mismatch():
    # The record's manufacturer differs from the claim, so this test would
    # fail if the reliability gate were wrong and let a comparison through.
    result = _result_for(UNRELIABLE_RECORD_NO_EXCERPT)
    assert result.record_reliable is False
    manufacturer = next(f for f in result.field_results if f.field == "manufacturer")
    assert manufacturer.result == FieldMatch.unknown
    assert all(f.result != FieldMatch.mismatch for f in result.field_results)
    assert result.overall == IdentityResult.unverified


def test_unreliable_record_wrong_source_type_never_yields_mismatch():
    # Same differing-values setup as above, but reliability fails on source_type.
    result = _result_for(UNRELIABLE_RECORD_WRONG_SOURCE_TYPE)
    assert result.record_reliable is False
    manufacturer = next(f for f in result.field_results if f.field == "manufacturer")
    assert manufacturer.result == FieldMatch.unknown
    assert all(f.result != FieldMatch.mismatch for f in result.field_results)
    assert result.overall == IdentityResult.unverified


def test_claim_missing_registration_no_is_unknown_for_that_field():
    result = _result_for(CLAIM_MISSING_REGISTRATION_NO)
    registration = next(f for f in result.field_results if f.field == "registration_no")
    assert registration.result == FieldMatch.unknown


def test_registration_differs_only_by_case_spaces_hyphens_is_match():
    result = _result_for(REGISTRATION_CASE_HYPHEN_DIFFERENCE)
    registration = next(f for f in result.field_results if f.field == "registration_no")
    assert registration.result == FieldMatch.match


def test_registration_differs_in_digits_is_mismatch():
    claim = _matching_claim(registration_no="R-41234568")
    record = _reliable_record(registration_no="R41234567")
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    registration = next(f for f in result.field_results if f.field == "registration_no")
    assert registration.result == FieldMatch.mismatch
    assert result.overall == IdentityResult.contradiction_detected


def test_mismatch_only_on_optional_brand_is_unverified_not_contradiction():
    result = _result_for(OPTIONAL_FIELD_MISMATCH_ONLY)
    brand = next(f for f in result.field_results if f.field == "brand")
    assert brand.result == FieldMatch.mismatch
    assert result.overall == IdentityResult.unverified
    assert result.conflicts == ["brand"]


def test_same_inputs_same_output_is_deterministic():
    first = _result_for(SAME_INPUTS_SAME_OUTPUT)
    second = _result_for(SAME_INPUTS_SAME_OUTPUT)
    assert first == second


def test_evidence_ids_from_record_appear_in_result():
    result = _result_for(FULL_MATCH)
    assert FULL_MATCH.record.evidence_id in result.evidence_ids


def test_seller_request_list_contains_claimed_model_and_manufacturer_on_conflict():
    claim = _matching_claim(model="BT-999", manufacturer="Totally Different Corp")
    record = _reliable_record(model_scope=["BT-100"], manufacturer="Acme Electronics Co")
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    joined = " ".join(result.seller_request_list)
    assert "BT-999" in joined
    assert "Totally Different Corp" in joined
    # No value from the record (rather than the claim) is ever asked about.
    assert "BT-100" not in joined
    assert "Acme Electronics Co" not in joined


def test_seller_request_list_never_invents_values():
    # manufacturer mismatches but the claim itself has no model at all.
    claim = _matching_claim(manufacturer="Totally Different Corp", model=None)
    record = _reliable_record(manufacturer="Acme Electronics Co", model_scope=[])
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    joined = " ".join(result.seller_request_list)
    assert "model" not in joined.lower()
    assert "BT-" not in joined


def test_claim_with_no_model_produces_no_model_sentence_even_with_mismatch():
    claim = CertClaim(
        registration_no="R-41234567", manufacturer="Acme Electronics Ltd",
        factory_location="Shenzhen", category="Bluetooth speaker", model=None, brand="Acme",
    )
    record = _reliable_record(model_scope=["BT-100"])
    # model is unknown (claim side missing) which is a flagged required field.
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    model_field = next(f for f in result.field_results if f.field == "model_scope")
    assert model_field.result == FieldMatch.unknown
    joined = " ".join(result.seller_request_list)
    assert "model" not in joined.lower()
    assert "BT-100" not in joined


def test_no_manufacturer_on_claim_with_manufacturer_on_record_is_unknown_not_mismatch():
    claim = _matching_claim(manufacturer=None)
    record = _reliable_record(manufacturer="Acme Electronics Co")
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    manufacturer = next(f for f in result.field_results if f.field == "manufacturer")
    assert manufacturer.result == FieldMatch.unknown
    assert all(f.result != FieldMatch.mismatch for f in result.field_results if f.field == "manufacturer")
    assert result.overall != IdentityResult.contradiction_detected


# ---------------------------------------------------------------------------
# Design answer 5: a value missing on either side is unknown for every field
# ---------------------------------------------------------------------------

def test_registration_missing_on_record_is_unknown():
    claim = _matching_claim(registration_no="R-41234567")
    record = _reliable_record(registration_no=None)
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    registration = next(f for f in result.field_results if f.field == "registration_no")
    assert registration.result == FieldMatch.unknown


def test_factory_location_missing_on_claim_is_unknown():
    claim = _matching_claim(factory_location=None)
    record = _reliable_record(factory_location="Shenzhen")
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    factory = next(f for f in result.field_results if f.field == "factory_location")
    assert factory.result == FieldMatch.unknown


def test_category_missing_on_record_is_unknown():
    claim = _matching_claim(category="Bluetooth speaker")
    record = _reliable_record(category=None)
    result = verify_certification(claim, record, date(2025, 1, 1), CONFIG)
    category = next(f for f in result.field_results if f.field == "category")
    assert category.result == FieldMatch.unknown


# ---------------------------------------------------------------------------
# Validity boundaries
# ---------------------------------------------------------------------------

def test_as_of_equal_to_valid_from_is_valid():
    record = _reliable_record(valid_from=date(2025, 1, 1), valid_to=date(2026, 1, 1))
    result = verify_certification(_matching_claim(), record, date(2025, 1, 1), CONFIG)
    validity = next(f for f in result.field_results if f.field == "validity")
    assert validity.result == FieldMatch.match


def test_as_of_equal_to_valid_to_is_valid():
    record = _reliable_record(valid_from=date(2025, 1, 1), valid_to=date(2026, 1, 1))
    result = verify_certification(_matching_claim(), record, date(2026, 1, 1), CONFIG)
    validity = next(f for f in result.field_results if f.field == "validity")
    assert validity.result == FieldMatch.match


def test_as_of_one_day_before_valid_from_is_invalid():
    record = _reliable_record(valid_from=date(2025, 1, 1), valid_to=date(2026, 1, 1))
    result = verify_certification(_matching_claim(), record, date(2024, 12, 31), CONFIG)
    validity = next(f for f in result.field_results if f.field == "validity")
    assert validity.result == FieldMatch.mismatch


def test_as_of_one_day_after_valid_to_is_invalid():
    record = _reliable_record(valid_from=date(2025, 1, 1), valid_to=date(2026, 1, 1))
    result = verify_certification(_matching_claim(), record, date(2026, 1, 2), CONFIG)
    validity = next(f for f in result.field_results if f.field == "validity")
    assert validity.result == FieldMatch.mismatch


def test_validity_missing_dates_on_reliable_record_is_unknown():
    record = _reliable_record(valid_from=None, valid_to=None, status=None)
    result = verify_certification(_matching_claim(), record, date(2025, 1, 1), CONFIG)
    validity = next(f for f in result.field_results if f.field == "validity")
    assert validity.result == FieldMatch.unknown


# ---------------------------------------------------------------------------
# "fraud" / "fake" must never appear in any output string
# ---------------------------------------------------------------------------

def test_no_fraud_or_fake_in_any_fixture_case_output():
    banned = {"fraud", "fake"}
    for case in ALL_CASES:
        result = _result_for(case)
        texts = [result.reasoning] + result.seller_request_list + [
            f.reason for f in result.field_results
        ]
        for text in texts:
            lowered = text.lower()
            for word in banned:
                assert word not in lowered, f"{case.name}: banned word {word!r} in {text!r}"


# ---------------------------------------------------------------------------
# AST check
# ---------------------------------------------------------------------------

_FORBIDDEN_NAMES = {
    "random", "socket", "requests", "httpx", "os", "pathlib", "time", "eval", "exec",
}

# Clock reads are blocked; importing the datetime type for hints is allowed.
_FORBIDDEN_CLOCK_CALLS = (".now(", ".utcnow(", ".today(", "datetime.datetime(", "time.time(")


def test_engine_module_has_no_forbidden_imports_or_calls():
    module_path = (
        Path(__file__).resolve().parent.parent
        / "app" / "decision" / "verification_engine.py"
    )
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source)

    used_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                used_names.add(node.module.split(".")[0])
            for alias in node.names:
                name = alias.asname or alias.name
                used_names.add(name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                used_names.add(name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            used_names.add(node.id)
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            used_names.add(node.func.id)

    clock_calls = [s for s in _FORBIDDEN_CLOCK_CALLS if s in source]
    assert not clock_calls, f"verification_engine.py must not read the clock: {clock_calls}"
    forbidden_found = used_names & _FORBIDDEN_NAMES
    assert not forbidden_found, f"forbidden names used: {forbidden_found}"


# ---------------------------------------------------------------------------
# Config checks (engine-facing; normaliser-level config checks already exist
# in test_verification_normalizers.py and are not repeated here)
# ---------------------------------------------------------------------------

def _base_config_data():
    return {
        "fuzzy_threshold": 0.85,
        "legal_suffixes": ["co", "ltd", "limited", "llc", "inc", "corp", "corporation",
                            "pvt", "private", "gmbh", "sa", "plc", "company"],
        "inactive_statuses": ["cancelled", "suspended", "expired", "withdrawn", "revoked"],
        "required_fields": ["registration_no", "manufacturer", "model_scope", "validity"],
        "optional_fields": ["factory_location", "category", "brand"],
    }


def test_config_fuzzy_threshold_zero_rejected():
    data = _base_config_data()
    data["fuzzy_threshold"] = 0.0
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_fuzzy_threshold_one_rejected():
    data = _base_config_data()
    data["fuzzy_threshold"] = 1.0
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_unknown_field_name_rejected():
    data = _base_config_data()
    data["required_fields"] = ["not_a_real_field"]
    with pytest.raises(ValidationError):
        parse_verification_config(data)


def test_config_required_optional_overlap_rejected():
    data = _base_config_data()
    data["optional_fields"] = ["manufacturer"]
    with pytest.raises(ValidationError):
        parse_verification_config(data)
