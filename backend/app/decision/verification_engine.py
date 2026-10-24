"""Verification engine: certification identity match (PRD B8).

See docs/decisions.md section 6, Part 2. Pure function, no I/O, no network,
no randomness, no eval/exec. The only timestamp used is the `as_of` date the
caller passes in; the engine never reads the clock.

Imports: `date` and `datetime` from `datetime` for type use only, `difflib` for fuzzy name
comparison, and the Step 3a config/normalisers/enums modules.
"""
from dataclasses import dataclass, field as dataclass_field
from datetime import date, datetime
from difflib import SequenceMatcher
from typing import List, Optional

from app.decision.enums import FieldMatch, IdentityResult
from app.decision.verification_config import VerificationConfig
from app.decision.verification_normalizers import (
    model_matches_scope,
    normalize_name,
    normalize_registration,
)

# Field keys, matching app.decision.verification_config.KNOWN_FIELDS.
_NAME_FIELDS = ("manufacturer", "factory_location", "category", "brand")


@dataclass(frozen=True)
class CertClaim:
    """The seller's certification claim, as extracted from the listing."""

    registration_no: Optional[str] = None
    manufacturer: Optional[str] = None
    factory_location: Optional[str] = None
    category: Optional[str] = None
    model: Optional[str] = None
    brand: Optional[str] = None


@dataclass(frozen=True)
class CertRecord:
    """An official registry record. Not a claim: this is what was retrieved."""

    registration_no: Optional[str] = None
    manufacturer: Optional[str] = None
    factory_location: Optional[str] = None
    category: Optional[str] = None
    model_scope: List[str] = dataclass_field(default_factory=list)
    brand: Optional[str] = None
    valid_from: Optional[date] = None
    valid_to: Optional[date] = None
    status: Optional[str] = None
    source_type: Optional[str] = None
    source_url: Optional[str] = None
    evidence_id: Optional[str] = None
    excerpt: Optional[str] = None
    retrieved_at: Optional[datetime] = None


@dataclass(frozen=True)
class FieldComparison:
    field: str
    claim_value: Optional[str]
    record_value: Optional[str]
    result: FieldMatch
    reason: str


@dataclass(frozen=True)
class VerificationResult:
    overall: IdentityResult
    field_results: List[FieldComparison]
    conflicts: List[str]
    record_reliable: bool
    evidence_ids: List[str]
    reasoning: str
    seller_request_list: List[str]


def _is_reliable(record: Optional[CertRecord]) -> bool:
    if record is None:
        return False
    return bool(
        record.source_type == "official_portal"
        and record.excerpt
        and record.evidence_id
    )


def _compare_registration(claim_val: Optional[str], record_val: Optional[str]) -> FieldComparison:
    if claim_val is None or record_val is None:
        return FieldComparison(
            "registration_no", claim_val, record_val, FieldMatch.unknown,
            "value missing on the claim or the record",
        )
    norm_claim = normalize_registration(claim_val)
    norm_record = normalize_registration(record_val)
    if norm_claim is None or norm_record is None:
        return FieldComparison(
            "registration_no", claim_val, record_val, FieldMatch.unknown,
            "value empty after normalisation",
        )
    if norm_claim == norm_record:
        return FieldComparison(
            "registration_no", claim_val, record_val, FieldMatch.match,
            "normalised registration numbers are equal",
        )
    return FieldComparison(
        "registration_no", claim_val, record_val, FieldMatch.mismatch,
        "normalised registration numbers differ",
    )


def _compare_name_field(
    field: str, claim_val: Optional[str], record_val: Optional[str], config: VerificationConfig
) -> FieldComparison:
    if claim_val is None or record_val is None:
        return FieldComparison(
            field, claim_val, record_val, FieldMatch.unknown,
            "value missing on the claim or the record",
        )
    norm_claim = normalize_name(claim_val, config.legal_suffixes)
    norm_record = normalize_name(record_val, config.legal_suffixes)
    if norm_claim is None or norm_record is None:
        return FieldComparison(
            field, claim_val, record_val, FieldMatch.unknown,
            "value empty after normalisation",
        )
    if norm_claim == norm_record:
        return FieldComparison(
            field, claim_val, record_val, FieldMatch.match,
            "normalised values are equal",
        )
    ratio = SequenceMatcher(None, norm_claim, norm_record).ratio()
    if ratio >= config.fuzzy_threshold:
        return FieldComparison(
            field, claim_val, record_val, FieldMatch.partial,
            f"fuzzy match above threshold (ratio {ratio:.2f})",
        )
    return FieldComparison(
        field, claim_val, record_val, FieldMatch.mismatch,
        f"below fuzzy threshold (ratio {ratio:.2f})",
    )


def _compare_model_scope(claim_model: Optional[str], record_scope: List[str]) -> FieldComparison:
    record_value = ", ".join(record_scope) if record_scope else None
    outcome = model_matches_scope(claim_model, record_scope)
    if outcome is None:
        return FieldComparison(
            "model_scope", claim_model, record_value, FieldMatch.unknown,
            "model missing on the claim, or scope missing on the record",
        )
    if outcome:
        return FieldComparison(
            "model_scope", claim_model, record_value, FieldMatch.match,
            "claimed model is within the record's model scope",
        )
    return FieldComparison(
        "model_scope", claim_model, record_value, FieldMatch.mismatch,
        "claimed model is not within the record's model scope",
    )


def _compare_validity(record: CertRecord, as_of: date, config: VerificationConfig) -> FieldComparison:
    record_value = f"valid_from={record.valid_from} valid_to={record.valid_to} status={record.status}"
    if record.valid_from is None or record.valid_to is None or record.status is None:
        return FieldComparison(
            "validity", None, record_value, FieldMatch.unknown,
            "validity dates or status missing on the record",
        )
    inactive = {s.lower() for s in config.inactive_statuses}
    in_range = record.valid_from <= as_of <= record.valid_to
    active = record.status.lower() not in inactive
    if in_range and active:
        return FieldComparison(
            "validity", None, record_value, FieldMatch.match,
            "as_of is within the validity window and the status is active",
        )
    reason = "status is inactive" if not active else "as_of is outside the validity window"
    return FieldComparison("validity", None, record_value, FieldMatch.mismatch, reason)


def _unknown_for_missing_record(field: str, claim_val: Optional[str]) -> FieldComparison:
    return FieldComparison(
        field, claim_val, None, FieldMatch.unknown,
        "no reliable record to compare against",
    )


def _build_seller_request_list(claim: CertClaim, flagged_fields: set) -> List[str]:
    sentences: List[str] = []
    if "registration_no" in flagged_fields and claim.registration_no:
        sentences.append(
            f"Ask the seller for official evidence of the registration number {claim.registration_no}."
        )
    if "manufacturer" in flagged_fields and claim.manufacturer:
        sentences.append(
            f"Ask the seller for evidence that the manufacturer is {claim.manufacturer}."
        )
    if "model_scope" in flagged_fields and claim.model:
        sentences.append(
            f"Ask the seller for the registration covering model {claim.model}."
        )
    if "validity" in flagged_fields:
        sentences.append("Ask the seller for the registration's current validity dates.")
    if "factory_location" in flagged_fields and claim.factory_location:
        sentences.append(
            f"Ask the seller for evidence that the factory location is {claim.factory_location}."
        )
    if "category" in flagged_fields and claim.category:
        sentences.append(
            f"Ask the seller for evidence that the category is {claim.category}."
        )
    if "brand" in flagged_fields and claim.brand:
        sentences.append(
            f"Ask the seller for evidence that the brand is {claim.brand}."
        )
    return sentences


def verify_certification(
    claim: CertClaim,
    record: Optional[CertRecord],
    as_of: date,
    config: VerificationConfig,
) -> VerificationResult:
    """Compare a seller's certification claim against a registry record.

    Pure function: no clock, no network, no file I/O. `as_of` is the only
    date used, supplied by the caller.
    """
    reliable = _is_reliable(record)
    evidence_ids = [record.evidence_id] if record is not None and record.evidence_id else []

    if not reliable:
        claim_values = {
            "registration_no": claim.registration_no,
            "manufacturer": claim.manufacturer,
            "factory_location": claim.factory_location,
            "category": claim.category,
            "model_scope": claim.model,
            "brand": claim.brand,
            "validity": None,
        }
        all_fields = list(config.required_fields) + list(config.optional_fields)
        field_results = [
            _unknown_for_missing_record(f, claim_values.get(f)) for f in all_fields
        ]
        flagged = set(config.required_fields)
        seller_request_list = _build_seller_request_list(claim, flagged)
        reason = "no record was supplied" if record is None else "the record is not reliable evidence"
        return VerificationResult(
            overall=IdentityResult.unverified,
            field_results=field_results,
            conflicts=[],
            record_reliable=False,
            evidence_ids=evidence_ids,
            reasoning=f"Could not verify: {reason}, so every field is unknown.",
            seller_request_list=seller_request_list,
        )

    results_by_field = {
        "registration_no": _compare_registration(claim.registration_no, record.registration_no),
        "manufacturer": _compare_name_field("manufacturer", claim.manufacturer, record.manufacturer, config),
        "factory_location": _compare_name_field(
            "factory_location", claim.factory_location, record.factory_location, config
        ),
        "category": _compare_name_field("category", claim.category, record.category, config),
        "model_scope": _compare_model_scope(claim.model, record.model_scope),
        "brand": _compare_name_field("brand", claim.brand, record.brand, config),
        "validity": _compare_validity(record, as_of, config),
    }
    field_results = [results_by_field[f] for f in _ordered_fields(config)]

    required_results = {f: results_by_field[f] for f in config.required_fields}
    optional_results = {f: results_by_field[f] for f in config.optional_fields}

    required_mismatch = {f for f, c in required_results.items() if c.result == FieldMatch.mismatch}
    optional_mismatch = {f for f, c in optional_results.items() if c.result == FieldMatch.mismatch}
    required_unknown_or_partial = {
        f for f, c in required_results.items() if c.result in (FieldMatch.unknown, FieldMatch.partial)
    }

    conflicts = sorted(required_mismatch | optional_mismatch)
    # Union of every mismatched field and every unknown/partial required field,
    # regardless of which overall-result branch fires: "one sentence per
    # conflict or unknown required field" (docs/decisions.md section 6).
    flagged = required_mismatch | optional_mismatch | required_unknown_or_partial

    if required_mismatch:
        overall = IdentityResult.contradiction_detected
        reasoning = (
            "Potential certification mismatch: a reliable record contradicts the claim on "
            + ", ".join(sorted(required_mismatch)) + "."
        )
    elif optional_mismatch:
        overall = IdentityResult.unverified
        reasoning = (
            "Could not verify: the record disagrees with the claim on optional field(s) "
            + ", ".join(sorted(optional_mismatch)) + "."
        )
    elif required_unknown_or_partial:
        overall = IdentityResult.unverified
        reasoning = (
            "Could not verify: required field(s) "
            + ", ".join(sorted(required_unknown_or_partial))
            + " could not be confirmed against the record."
        )
    else:
        overall = IdentityResult.verified
        reasoning = "All required fields matched a reliable, currently valid record."

    seller_request_list = _build_seller_request_list(claim, flagged)

    return VerificationResult(
        overall=overall,
        field_results=field_results,
        conflicts=conflicts,
        record_reliable=True,
        evidence_ids=evidence_ids,
        reasoning=reasoning,
        seller_request_list=seller_request_list,
    )


def _ordered_fields(config: VerificationConfig) -> List[str]:
    return list(config.required_fields) + list(config.optional_fields)
