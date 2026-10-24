"""Full report schema (PRD B5). This is the frontend contract; see docs/decisions.md section 9.

Python fields are snake_case; JSON keys are camelCase (serialise with `by_alias=True`,
or use `FullReport.to_frontend()`). Enum values stay lowercase (decisions.md section 1).
Money is Decimal and serialises as a string. Only existing enums are used.
"""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Literal, Optional, Set, Union

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr, field_validator, model_validator
from pydantic.alias_generators import to_camel

from app.decision.cost_config import DecimalIn
from app.decision.enums import (
    CheckStatus,
    ClassificationStatus,
    Confidence,
    FactKind,
    FieldMatch,
    IdentityResult,
    Outcome,
    RiskLevel,
)
from app.decision.rates.provenance import EvidenceKind, Provenance

DISCLAIMER = "Decision support only. Not legal clearance or customs approval."

SourceType = Literal["listing", "official_portal", "user_upload", "rule_source"]
FactValue = Union[StrictBool, StrictInt, StrictStr, DecimalIn]


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, alias_generator=to_camel, populate_by_name=True)


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class ProductFact(_ReportModel):
    field: str = Field(min_length=1)
    value: FactValue
    kind: FactKind
    evidence_id: Optional[str] = None


class ProductProfile(_ReportModel):
    confirmed: List[ProductFact] = []
    seller_claims: List[ProductFact] = []
    user_supplied: List[ProductFact] = []

    @model_validator(mode="after")
    def _check_kinds(self) -> "ProductProfile":
        for facts, kind in ((self.confirmed, FactKind.confirmed), (self.seller_claims, FactKind.seller_claim),
                            (self.user_supplied, FactKind.user_supplied)):
            wrong = [f.field for f in facts if f.kind is not kind]
            if wrong:
                raise ValueError(f"facts in the {kind.value} list have a different kind: " + ", ".join(wrong))
        missing = [f.field for f in self.confirmed if not f.evidence_id]
        if missing:
            raise ValueError("confirmed facts need an evidence_id: " + ", ".join(missing))
        return self

    def evidence_ids(self) -> Set[str]:
        return {f.evidence_id for f in self.confirmed + self.seller_claims + self.user_supplied if f.evidence_id}


# ---------------------------------------------------------------------------
# Checks and certification comparison
# ---------------------------------------------------------------------------

class RequirementCheckReport(_ReportModel):
    rule_id: str
    area: str
    status: CheckStatus
    reasoning: str
    rule_version: str
    evidence_ids: List[str]
    mandatory: bool
    requires_evidence: List[str]


class ReportFieldComparison(_ReportModel):
    field: str
    claim_value: Optional[str]
    record_value: Optional[str]
    result: FieldMatch
    reason: str


class CertificationComparisonReport(_ReportModel):
    result: IdentityResult
    field_results: List[ReportFieldComparison]
    conflicts: List[str]
    record_reliable: bool
    evidence_ids: List[str]
    reasoning: str
    seller_request_list: List[str]


# ---------------------------------------------------------------------------
# Cost
# ---------------------------------------------------------------------------

class ReportCostLine(_ReportModel):
    label: str
    kind: str
    base: Optional[Decimal] = None
    rate_pct: Optional[Decimal] = None
    amount: Decimal


class ReportAssumption(_ReportModel):
    name: str
    value: Optional[Decimal] = None
    source: str
    as_of: Optional[str] = None
    verified: bool
    user_supplied: bool = False
    owner: Optional[str] = None
    note: Optional[str] = None
    stale: Optional[bool] = None
    age_days: Optional[int] = None
    max_age_days: Optional[int] = None
    provenance: Optional[Provenance] = None
    evidence_kind: Optional[EvidenceKind] = None


class ReportCost(_ReportModel):
    label: str
    currency: str
    quantity: int
    low: Decimal
    expected: Decimal
    high: Decimal
    per_unit_low: Decimal
    per_unit_expected: Decimal
    per_unit_high: Decimal
    breakdown: List[ReportCostLine]
    assumptions: List[ReportAssumption]
    breakdown_note: str
    rates_verified: bool
    methodology_unverified: bool
    unverified_assumptions: bool
    any_stale: bool
    staleness_checked: bool
    any_human_approved: bool
    rates_verified_count: int
    rates_total: int
    assumptions_version: str
    assumptions_effective_date: str


# ---------------------------------------------------------------------------
# Evidence, actions, summary
# ---------------------------------------------------------------------------

class EvidenceItem(_ReportModel):
    id: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    retrieved_at: datetime
    excerpt: Optional[str] = None
    source_type: SourceType

    @field_validator("retrieved_at")
    @classmethod
    def _check_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("retrieved_at must be timezone-aware")
        return value


class NextAction(_ReportModel):
    priority: int = Field(ge=1)  # 1 = most urgent
    text: str = Field(min_length=1)


class SummaryClassification(_ReportModel):
    value: Optional[str]  # category id; friendly labels are a frontend concern
    status: ClassificationStatus
    confidence: Confidence
    candidate_hs_codes: List[str]  # suggestions only, never verified


class SummaryCost(_ReportModel):
    currency: str
    expected: Decimal


class ReportSummary(_ReportModel):
    quantity: Optional[int]
    classification: Optional[SummaryClassification]
    bis: Optional[CheckStatus]
    wireless: Optional[CheckStatus]
    seller_claims_bis: bool
    identity_match: IdentityResult
    illustrative_cost_per_unit: Optional[SummaryCost]


# ---------------------------------------------------------------------------
# Full report
# ---------------------------------------------------------------------------

class FullReport(_ReportModel):
    id: str = Field(min_length=1)
    outcome: Outcome
    risk_level: RiskLevel
    score: int
    next_action: Optional[str]
    next_actions: List[NextAction]
    reasons: List[str]
    summary: ReportSummary
    profile: ProductProfile
    checks: List[RequirementCheckReport]
    certification_comparison: Optional[CertificationComparisonReport]
    cost: Optional[ReportCost]
    evidence: List[EvidenceItem]
    rule_versions: List[str]
    questions_skipped: List[str]
    disclaimer: Literal[DISCLAIMER] = DISCLAIMER  # the only accepted value

    @model_validator(mode="after")
    def _check_evidence_ids(self) -> "FullReport":
        ids = [e.id for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence id")
        referenced = set(self.profile.evidence_ids())
        for check in self.checks:
            referenced.update(check.evidence_ids)
        if self.certification_comparison is not None:
            referenced.update(self.certification_comparison.evidence_ids)
        dangling = sorted(referenced - set(ids))
        if dangling:
            raise ValueError("evidence ids referenced but not in evidence: " + ", ".join(dangling))
        return self

    def to_frontend(self) -> Dict[str, Any]:
        """JSON-ready dict with camelCase keys, the shape the frontend reads."""
        return self.model_dump(mode="json", by_alias=True)
