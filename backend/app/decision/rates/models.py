"""Rate evidence models: candidates, evidence packs, proposals, approved records and store events.

Page text (excerpts, URLs) is untrusted data. It is stored and shown to the reviewer, never interpreted as
instructions; the checks only use the typed fields below. Decimal values reject floats and bools at the
boundary (same DecimalIn as cost_config). Datetimes must be timezone-aware and are supplied by the caller.
"""
import hashlib
import json
from decimal import Decimal
from enum import Enum
from typing import Annotated, List, Literal, Optional, Tuple, Union
from urllib.parse import urlsplit

from pydantic import (
    AfterValidator,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.decision.cost_config import CostAssumptions, DecimalIn
from app.decision.rates.provenance import EvidenceKind, Provenance  # noqa: F401  (Provenance re-exported)

EXCERPT_MAX_CHARS = 2000
# Benchmark keys that update several config entries in one atomic step.
RANGE_KEYS = {"default_freight_inr": ("default_freight_low_inr", "default_freight_high_inr")}


def config_fields() -> Tuple[str, ...]:
    """Assumption entry names in cost_assumptions.yaml (other_duties excluded)."""
    return tuple(name for name in CostAssumptions.model_fields if name != "other_duties")


def target_fields(rate_key: str) -> Tuple[str, ...]:
    """Config entries a rate_key updates. KeyError for a key that matches no updatable config entry."""
    if rate_key in RANGE_KEYS:
        return RANGE_KEYS[rate_key]
    range_targets = {name for names in RANGE_KEYS.values() for name in names}
    if rate_key in config_fields() and rate_key not in range_targets:
        return (rate_key,)
    raise KeyError(f"rate_key {rate_key!r} matches no updatable config entry")


def normalise_host(url: str) -> Optional[str]:
    """Lowercased host with userinfo, port and a trailing dot removed; None when the URL has no host."""
    try:
        host = urlsplit(url).hostname
    except ValueError:
        return None
    if not host:
        return None
    return host.rstrip(".") or None


def url_scheme(url: str) -> str:
    try:
        return urlsplit(url).scheme.lower()
    except ValueError:
        return ""


def derive_id(prefix: str, *parts: str) -> str:
    """Deterministic identifier from its inputs (same inputs give the same id)."""
    return prefix + hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:20]


def _non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be empty")
    return value.strip()


NonEmptyStr = Annotated[str, AfterValidator(_non_empty)]


class RateKind(str, Enum):
    statutory = "statutory"
    benchmark = "benchmark"


class ProposalStatus(str, Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"
    superseded = "superseded"


class Severity(str, Enum):
    hard = "hard"  # rejects the whole candidate set
    warning = "warning"  # proposal is created but flagged; approval needs acknowledgement
    info = "info"  # recorded only (e.g. one source excluded)


class SourceRole(str, Enum):
    primary = "primary"
    agreeing = "agreeing"
    disagreeing = "disagreeing"
    sample = "sample"
    outlier = "outlier"
    excluded = "excluded"


class ReasonCode(str, Enum):
    no_authoritative_source = "no_authoritative_source"
    conflicting_official_sources = "conflicting_official_sources"
    rate_key_mismatch = "rate_key_mismatch"
    kind_mismatch = "kind_mismatch"
    unit_mismatch = "unit_mismatch"
    out_of_bounds = "out_of_bounds"
    number_not_in_excerpt = "number_not_in_excerpt"
    bad_effective_date = "bad_effective_date"
    older_than_current = "older_than_current"
    insufficient_samples = "insufficient_samples"
    insufficient_domains = "insufficient_domains"
    spread_too_wide = "spread_too_wide"
    fetch_error = "fetch_error"


class Candidate(BaseModel):
    """One value seen on one page, as returned by a fetcher. Every field is untrusted input."""

    model_config = ConfigDict(extra="forbid")

    rate_key: str
    kind: RateKind
    value: DecimalIn = Field(ge=0)
    unit: str
    currency: Optional[str] = None
    effective_date: Optional[str] = None  # ISO date; checked by checks.check_effective_date, optional for benchmarks
    source_url: str
    source_tier: StrictInt = Field(ge=1, le=3)  # claimed by the fetcher; the checks recompute it from policy
    excerpt: str
    snapshot_ref: Optional[str] = None
    retrieved_at: AwareDatetime
    fetch_id: str
    is_fixture: StrictBool = False  # set by FixtureFetcher: test data, not real evidence

    @field_validator("source_url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        if url_scheme(value) not in ("http", "https") or normalise_host(value) is None:
            raise ValueError("source_url must be an http(s) URL with a host")
        return value


class CheckResult(BaseModel):
    name: str
    passed: bool
    detail: str
    severity: Severity = Severity.info
    reason_code: Optional[ReasonCode] = None
    subject: Optional[str] = None  # source URL the check applied to; None for checks on the whole set


class SourceRef(BaseModel):
    url: str
    domain: str
    tier: int  # from policy domain lists
    claimed_tier: int  # as given by the fetcher
    role: SourceRole
    value: Decimal
    unit: str
    effective_date: Optional[str] = None
    retrieved_at: AwareDatetime
    excerpt: str  # capped at EXCERPT_MAX_CHARS
    excerpt_truncated: bool = False
    snapshot_ref: Optional[str] = None
    fetch_id: str
    fixture: bool = False  # came from FixtureFetcher: not real evidence


class Disagreement(BaseModel):
    url: str
    domain: str
    tier: int
    value: Decimal
    proposed_value: Decimal
    detail: str


class DomainMedian(BaseModel):
    domain: str
    median: Decimal
    samples: int


class BenchmarkStats(BaseModel):
    low: Decimal
    median: Decimal
    high: Decimal
    sample_count: int  # valid samples from the domains kept
    raw_sample_count: int  # valid samples before outlier removal
    domain_count: int
    domains: List[str]
    domain_medians: List[DomainMedian]  # one point per domain (per-domain influence cap)
    outlier_domains: List[str] = Field(default_factory=list)
    spread_ratio: Decimal

    @model_validator(mode="after")
    def _ordered(self) -> "BenchmarkStats":
        if not (self.low <= self.median <= self.high):
            raise ValueError("benchmark stats must satisfy low <= median <= high")
        return self


class EvidencePack(BaseModel):
    rate_key: str
    kind: RateKind
    proposed_value: Decimal  # statutory value, or the benchmark median
    unit: str
    effective_date: Optional[str] = None  # statutory: from the official source; benchmark: latest retrieval date
    reconfirmation: bool = False  # same value as the approved record, newer effective date
    current_value: Optional[Decimal] = None
    current_effective_date: Optional[str] = None
    current_proposal_id: Optional[str] = None
    change_abs: Optional[Decimal] = None
    change_pct: Optional[Decimal] = None
    # Information only, shown when there is no approved baseline.
    placeholder_value: Optional[Decimal] = None
    placeholder_change_pct: Optional[Decimal] = None
    placeholder_detail: Optional[str] = None
    sources: List[SourceRef]
    agreeing_domains: int = 0  # distinct tier-2/3 domains agreeing with the official value
    corroboration: str
    disagreements: List[Disagreement] = Field(default_factory=list)
    benchmark: Optional[BenchmarkStats] = None
    check_results: List[CheckResult]
    warnings: List[str] = Field(default_factory=list)
    fixture_data: bool = False  # any source is fixture data; approval needs an explicit --allow-fixture
    content_hash: str = ""


def pack_hash(pack: EvidencePack) -> str:
    """SHA-256 over the canonical JSON of the pack, excluding content_hash itself."""
    data = pack.model_dump(mode="json", exclude={"content_hash"})
    blob = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Proposal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    proposal_id: str
    rate_key: str
    kind: RateKind
    status: ProposalStatus = ProposalStatus.pending  # as stored: pending; the store derives the live status
    evidence_pack: EvidencePack
    created_at: AwareDatetime


class RejectionRecord(BaseModel):
    """A candidate set that failed a hard check (or could not be fetched). Logged; never a proposal."""

    rejection_id: str
    rate_key: str
    reason_code: ReasonCode
    reason_codes: List[ReasonCode]
    detail: str
    check_results: List[CheckResult] = Field(default_factory=list)
    sources: List[SourceRef] = Field(default_factory=list)
    created_at: AwareDatetime


class UnchangedResult(BaseModel):
    """Same value as the approved record with the same or an older effective date: no proposal."""

    rate_key: str
    value: Decimal
    effective_date: Optional[str] = None
    current_proposal_id: str
    detail: str


ProposalResult = Union[Proposal, RejectionRecord, UnchangedResult]


class RateRecord(BaseModel):
    """The latest APPROVED value for a rate_key, built from an approved proposal."""

    rate_key: str
    kind: RateKind
    evidence_kind: EvidenceKind
    value: Decimal  # statutory value, or benchmark median
    range_low: Optional[Decimal] = None  # benchmark low
    range_high: Optional[Decimal] = None  # benchmark high
    unit: str
    effective_date: str  # becomes as_of in the cost assumptions
    source: str  # official source URL, or a benchmark summary
    sample_count: Optional[int] = None
    domain_count: Optional[int] = None
    proposal_id: str
    approved_by: str  # self-reported in the MVP (no authentication)
    approved_at: AwareDatetime
    evidence_hash: str
    fixture: bool = False  # approved from fixture data (needed --allow-fixture)
    fallback_note: Optional[str] = None  # set when a later approval was ignored and this one is used instead


class ProposalCreated(BaseModel):
    event_type: Literal["proposal_created"] = "proposal_created"
    proposal: Proposal

    @model_validator(mode="after")
    def _pending(self) -> "ProposalCreated":
        if self.proposal.status is not ProposalStatus.pending:
            raise ValueError("a created proposal must be pending")
        return self


class ProposalApproved(BaseModel):
    event_type: Literal["proposal_approved"] = "proposal_approved"
    proposal_id: str
    approver: NonEmptyStr  # self-reported
    approved_at: AwareDatetime
    note: Optional[str] = None
    acknowledged_warnings: List[str] = Field(default_factory=list)
    evidence_hash: str  # the pack hash the approver saw
    fixture_allowed: bool = False  # the approver passed --allow-fixture for a fixture-data proposal


class ProposalRejected(BaseModel):
    event_type: Literal["proposal_rejected"] = "proposal_rejected"
    proposal_id: str
    reviewer: NonEmptyStr  # self-reported
    rejected_at: AwareDatetime
    reason: NonEmptyStr


class ProposalSuperseded(BaseModel):
    event_type: Literal["proposal_superseded"] = "proposal_superseded"
    proposal_id: str
    superseded_by: str
    superseded_at: AwareDatetime


class RejectionLogged(BaseModel):
    event_type: Literal["rejection_logged"] = "rejection_logged"
    rejection: RejectionRecord


Event = Annotated[
    Union[ProposalCreated, ProposalApproved, ProposalRejected, ProposalSuperseded, RejectionLogged],
    Field(discriminator="event_type"),
]
EVENT_ADAPTER: TypeAdapter = TypeAdapter(Event)
