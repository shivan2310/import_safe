"""Refresh rates: fetch candidates, build proposals, record them in the store.

refresh_rates never applies a value; it only creates PENDING proposals (or logs rejections). A person approves
proposals with the review CLI. `now` is supplied by the caller. A bad fetch never stops the refresh: it is
logged as a rejection with reason_code fetch_error. StoreCorruptionError is not caught (fail closed).
"""
from datetime import datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import List, Optional, Sequence, Tuple, Union

from pydantic import BaseModel, Field

from app.decision.cost_config import CostAssumptions, load_cost_assumptions
from app.decision.rates.builder import build_proposal
from app.decision.rates.fetcher import RateFetcher
from app.decision.rates.models import (
    RANGE_KEYS,
    Candidate,
    CheckResult,
    ProposalCreated,
    ProposalStatus,
    ProposalSuperseded,
    ReasonCode,
    RejectionLogged,
    RejectionRecord,
    Severity,
    UnchangedResult,
    derive_id,
    normalise_host,
    target_fields,
)
from app.decision.rates.policy import Policy
from app.decision.rates.store import RateStore

_MAX_ERROR_TEXT = 300


class RefreshOutcome(str, Enum):
    created = "created"
    reconfirmation = "reconfirmation"
    unchanged = "unchanged"
    rejected = "rejected"
    fetch_error = "fetch_error"
    budget_exhausted = "budget_exhausted"
    unknown_rate_key = "unknown_rate_key"
    already_recorded = "already_recorded"


class KeyResult(BaseModel):
    rate_key: str
    outcome: RefreshOutcome
    proposal_id: Optional[str] = None
    rejection_id: Optional[str] = None
    reason_code: Optional[ReasonCode] = None
    superseded: List[str] = Field(default_factory=list)
    detail: str = ""


class RefreshReport(BaseModel):
    results: List[KeyResult]
    runs_used: int
    domains_used: List[str]
    budget_exhausted: bool
    store_warnings: List[str] = Field(default_factory=list)


def placeholder_for(base: CostAssumptions, rate_key: str) -> Tuple[Optional[Decimal], Optional[str]]:
    """YAML placeholder for a rate_key, shown as information only when there is no approved baseline."""
    try:
        fields = target_fields(rate_key)
    except KeyError:
        return None, None
    if rate_key in RANGE_KEYS:
        low, high = (getattr(base, name).value for name in fields)
        return (low + high) / Decimal(2), f"YAML placeholder range {low} to {high}; midpoint shown"
    return getattr(base, fields[0]).value, "YAML placeholder, not verified"


def _validate_fetched(fetched) -> List[Candidate]:
    if not isinstance(fetched, (list, tuple)):
        raise TypeError(f"fetcher returned {type(fetched).__name__}, expected a list of Candidate")
    if any(not isinstance(c, Candidate) for c in fetched):
        raise TypeError("fetcher returned an item that is not a Candidate")
    return list(fetched)


def _fetch_error(rate_key: str, exc: Exception, now: datetime) -> RejectionRecord:
    text = f"{type(exc).__name__}: {str(exc)[:_MAX_ERROR_TEXT]}"
    detail = f"Fetch failed; nothing was proposed. {text}"
    return RejectionRecord(
        rejection_id=derive_id("rej_", rate_key, ReasonCode.fetch_error.value, text, now.isoformat()),
        rate_key=rate_key, reason_code=ReasonCode.fetch_error, reason_codes=[ReasonCode.fetch_error], detail=detail,
        check_results=[CheckResult(name="fetch", passed=False, severity=Severity.hard,
                                   reason_code=ReasonCode.fetch_error, detail=detail)],
        created_at=now,
    )


def refresh_rates(
    rate_keys: Sequence[str],
    fetcher: RateFetcher,
    policy: Policy,
    store: RateStore,
    now: datetime,
    base_config_path: Union[str, Path, None] = None,
) -> RefreshReport:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    base = load_cost_assumptions(base_config_path)
    results: List[KeyResult] = []
    runs = 0
    domains: set = set()
    exhausted = False

    for key in rate_keys:
        if exhausted or runs >= policy.max_runs_per_refresh or len(domains) >= policy.max_domains_per_refresh:
            exhausted = True
            results.append(KeyResult(rate_key=key, outcome=RefreshOutcome.budget_exhausted,
                                     detail="Refresh budget reached; this key was not fetched."))
            continue
        if key not in policy.rates:
            results.append(KeyResult(rate_key=key, outcome=RefreshOutcome.unknown_rate_key,
                                     detail="No policy entry for this rate_key; not fetched."))
            continue

        runs += 1
        try:
            candidates = _validate_fetched(fetcher.fetch(key))
        except Exception as exc:  # a bad fetch never stops the refresh
            rejection = _fetch_error(key, exc, now)
            store.append_event(RejectionLogged(rejection=rejection))
            results.append(KeyResult(rate_key=key, outcome=RefreshOutcome.fetch_error, reason_code=ReasonCode.fetch_error,
                                     rejection_id=rejection.rejection_id, detail=rejection.detail))
            continue
        domains.update(h for h in (normalise_host(c.source_url) for c in candidates) if h)

        current = store.latest_approved(key)
        placeholder_value, placeholder_detail = placeholder_for(base, key)
        result = build_proposal(key, candidates, current, policy, now, placeholder_value, placeholder_detail)

        if isinstance(result, UnchangedResult):
            results.append(KeyResult(rate_key=key, outcome=RefreshOutcome.unchanged, detail=result.detail))
        elif isinstance(result, RejectionRecord):
            store.append_event(RejectionLogged(rejection=result))
            results.append(KeyResult(rate_key=key, outcome=RefreshOutcome.rejected, rejection_id=result.rejection_id,
                                     reason_code=result.reason_code, detail=result.detail))
        elif store.get_proposal(result.proposal_id) is not None:
            results.append(KeyResult(rate_key=key, outcome=RefreshOutcome.already_recorded,
                                     proposal_id=result.proposal_id,
                                     detail="An identical proposal (same evidence and time) is already recorded."))
        else:
            older = [p.proposal_id for p in store.proposals(ProposalStatus.pending) if p.rate_key == key]
            store.append_event(ProposalCreated(proposal=result))
            for old in older:
                store.append_event(ProposalSuperseded(proposal_id=old, superseded_by=result.proposal_id,
                                                      superseded_at=now))
            outcome = RefreshOutcome.reconfirmation if result.evidence_pack.reconfirmation else RefreshOutcome.created
            results.append(KeyResult(rate_key=key, outcome=outcome, proposal_id=result.proposal_id, superseded=older,
                                     detail=f"Pending proposal with {len(result.evidence_pack.warnings)} warning(s)."))

    return RefreshReport(results=results, runs_used=runs, domains_used=sorted(domains), budget_exhausted=exhausted,
                         store_warnings=list(store.warnings))
