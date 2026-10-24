"""Named fixture cases for the verification engine tests.

Each case is (claim, record, as_of, expected_overall, expected_conflicts).
Pure data — no I/O, no clock reads (as_of is a literal date per case).
"""
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

from app.decision.enums import IdentityResult
from app.decision.verification_engine import CertClaim, CertRecord


@dataclass(frozen=True)
class VerificationCase:
    name: str
    claim: CertClaim
    record: Optional[CertRecord]
    as_of: date
    expected_overall: IdentityResult
    expected_conflicts: List[str]


def _reliable_record(**overrides) -> CertRecord:
    base = dict(
        registration_no="R41234567",
        manufacturer="Acme Electronics Co",
        factory_location="Shenzhen",
        category="Bluetooth speaker",
        model_scope=["BT-100"],
        brand="Acme",
        valid_from=date(2024, 1, 1),
        valid_to=date(2026, 1, 1),
        status="active",
        source_type="official_portal",
        source_url="https://registry.example.gov/r/41234567",
        evidence_id="ev_1",
        excerpt="Registration R41234567, Acme Electronics Co, valid 2024-01-01 to 2026-01-01.",
        retrieved_at=None,
    )
    base.update(overrides)
    return CertRecord(**base)


def _matching_claim(**overrides) -> CertClaim:
    base = dict(
        registration_no="R-41234567",
        manufacturer="Acme Electronics Ltd",
        factory_location="Shenzhen",
        category="Bluetooth speaker",
        model="BT-100",
        brand="Acme",
    )
    base.update(overrides)
    return CertClaim(**base)


AS_OF = date(2025, 1, 1)

FULL_MATCH = VerificationCase(
    name="full_match",
    claim=_matching_claim(),
    record=_reliable_record(),
    as_of=AS_OF,
    expected_overall=IdentityResult.verified,
    expected_conflicts=[],
)

LEGAL_SUFFIX_DIFFERENCE = VerificationCase(
    name="legal_suffix_difference",
    claim=_matching_claim(manufacturer="Acme Electronics Ltd"),
    record=_reliable_record(manufacturer="Acme Electronics Co"),
    as_of=AS_OF,
    expected_overall=IdentityResult.verified,
    expected_conflicts=[],
)

MANUFACTURER_PARTIAL = VerificationCase(
    name="manufacturer_partial",
    claim=_matching_claim(manufacturer="Acme Electronic Co"),
    record=_reliable_record(manufacturer="Acme Electronics Co"),
    as_of=AS_OF,
    expected_overall=IdentityResult.unverified,
    expected_conflicts=[],
)

MANUFACTURER_MISMATCH = VerificationCase(
    name="manufacturer_mismatch",
    claim=_matching_claim(manufacturer="Totally Different Corp"),
    record=_reliable_record(manufacturer="Acme Electronics Co"),
    as_of=AS_OF,
    expected_overall=IdentityResult.contradiction_detected,
    expected_conflicts=["manufacturer"],
)

WRONG_MODEL = VerificationCase(
    name="wrong_model",
    claim=_matching_claim(model="BT-999"),
    record=_reliable_record(model_scope=["BT-100"]),
    as_of=AS_OF,
    expected_overall=IdentityResult.contradiction_detected,
    expected_conflicts=["model_scope"],
)

MODEL_WILDCARD_MATCH = VerificationCase(
    name="model_wildcard_match",
    claim=_matching_claim(model="BT-150"),
    record=_reliable_record(model_scope=["BT-1xx"]),
    as_of=AS_OF,
    expected_overall=IdentityResult.verified,
    expected_conflicts=[],
)

MODEL_WILDCARD_MISS = VerificationCase(
    name="model_wildcard_miss",
    claim=_matching_claim(model="BT-200"),
    record=_reliable_record(model_scope=["BT-1xx"]),
    as_of=AS_OF,
    expected_overall=IdentityResult.contradiction_detected,
    expected_conflicts=["model_scope"],
)

EXPIRED_RECORD = VerificationCase(
    name="expired_record",
    claim=_matching_claim(),
    record=_reliable_record(valid_from=date(2020, 1, 1), valid_to=date(2021, 1, 1)),
    as_of=AS_OF,
    expected_overall=IdentityResult.contradiction_detected,
    expected_conflicts=["validity"],
)

NOT_YET_VALID = VerificationCase(
    name="not_yet_valid",
    claim=_matching_claim(),
    record=_reliable_record(valid_from=date(2026, 1, 1), valid_to=date(2027, 1, 1)),
    as_of=AS_OF,
    expected_overall=IdentityResult.contradiction_detected,
    expected_conflicts=["validity"],
)

CANCELLED_STATUS = VerificationCase(
    name="cancelled_status",
    claim=_matching_claim(),
    record=_reliable_record(status="cancelled"),
    as_of=AS_OF,
    expected_overall=IdentityResult.contradiction_detected,
    expected_conflicts=["validity"],
)

RECORD_NONE = VerificationCase(
    name="record_none",
    claim=_matching_claim(),
    record=None,
    as_of=AS_OF,
    expected_overall=IdentityResult.unverified,
    expected_conflicts=[],
)

UNRELIABLE_RECORD_NO_EXCERPT = VerificationCase(
    name="unreliable_record_no_excerpt",
    claim=_matching_claim(manufacturer="Claimed Corp"),
    record=_reliable_record(manufacturer="Completely Different Name", excerpt=None, evidence_id="ev_2"),
    as_of=AS_OF,
    expected_overall=IdentityResult.unverified,
    expected_conflicts=[],
)

UNRELIABLE_RECORD_WRONG_SOURCE_TYPE = VerificationCase(
    name="unreliable_record_wrong_source_type",
    claim=_matching_claim(manufacturer="Claimed Corp"),
    record=_reliable_record(manufacturer="Completely Different Name", source_type="listing"),
    as_of=AS_OF,
    expected_overall=IdentityResult.unverified,
    expected_conflicts=[],
)

CLAIM_MISSING_REGISTRATION_NO = VerificationCase(
    name="claim_missing_registration_no",
    claim=_matching_claim(registration_no=None),
    record=_reliable_record(),
    as_of=AS_OF,
    expected_overall=IdentityResult.unverified,
    expected_conflicts=[],
)

REGISTRATION_CASE_HYPHEN_DIFFERENCE = VerificationCase(
    name="registration_case_hyphen_difference",
    claim=_matching_claim(registration_no="r 41-234 567"),
    record=_reliable_record(registration_no="R41234567"),
    as_of=AS_OF,
    expected_overall=IdentityResult.verified,
    expected_conflicts=[],
)

OPTIONAL_FIELD_MISMATCH_ONLY = VerificationCase(
    name="optional_field_mismatch_only",
    claim=_matching_claim(brand="OtherBrand"),
    record=_reliable_record(brand="Acme"),
    as_of=AS_OF,
    expected_overall=IdentityResult.unverified,
    expected_conflicts=["brand"],
)

SAME_INPUTS_SAME_OUTPUT = VerificationCase(
    name="same_inputs_same_output",
    claim=_matching_claim(),
    record=_reliable_record(),
    as_of=AS_OF,
    expected_overall=IdentityResult.verified,
    expected_conflicts=[],
)

ALL_CASES = [
    FULL_MATCH,
    LEGAL_SUFFIX_DIFFERENCE,
    MANUFACTURER_PARTIAL,
    MANUFACTURER_MISMATCH,
    WRONG_MODEL,
    MODEL_WILDCARD_MATCH,
    MODEL_WILDCARD_MISS,
    EXPIRED_RECORD,
    NOT_YET_VALID,
    CANCELLED_STATUS,
    RECORD_NONE,
    UNRELIABLE_RECORD_NO_EXCERPT,
    UNRELIABLE_RECORD_WRONG_SOURCE_TYPE,
    CLAIM_MISSING_REGISTRATION_NO,
    REGISTRATION_CASE_HYPHEN_DIFFERENCE,
    OPTIONAL_FIELD_MISMATCH_ONLY,
    SAME_INPUTS_SAME_OUTPUT,
]
