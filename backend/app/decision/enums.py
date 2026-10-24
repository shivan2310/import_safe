"""Shared decision-layer enums. Values are lowercase snake_case; see docs/decisions.md."""
from enum import Enum


class CheckStatus(str, Enum):
    potentially_applicable = "potentially_applicable"
    verified = "verified"
    not_applicable = "not_applicable"
    unverified = "unverified"
    contradiction_detected = "contradiction_detected"


class ClassificationStatus(str, Enum):
    confirmed = "confirmed"
    needs_confirmation = "needs_confirmation"
    unsupported = "unsupported"


class FieldMatch(str, Enum):
    match = "match"
    partial = "partial"
    mismatch = "mismatch"
    unknown = "unknown"


class IdentityResult(str, Enum):
    verified = "verified"
    unverified = "unverified"
    contradiction_detected = "contradiction_detected"


class FactKind(str, Enum):
    confirmed = "confirmed"
    seller_claim = "seller_claim"
    user_supplied = "user_supplied"


class Confidence(str, Enum):
    high = "high"
    medium = "medium"
    low = "low"


class Outcome(str, Enum):
    likely_importable = "likely_importable"
    conditional_import = "conditional_import"
    high_risk_do_not_proceed = "high_risk_do_not_proceed"
    insufficient_information = "insufficient_information"


class RiskLevel(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class StageState(str, Enum):
    pending = "pending"
    running = "running"
    done = "done"
    needs_input = "needs_input"
    failed = "failed"
