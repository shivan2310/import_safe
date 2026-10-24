"""Pure proposal builder.

build_proposal(rate_key, candidates, current, policy, now) turns fetched candidates into a pending Proposal with
an evidence pack, a RejectionRecord (a hard check failed), or an UnchangedResult (same value as the approved
record, no newer effective date). It never reads the clock (it uses `now`), the network or any file.

Statutory rates need an official (tier-1, https) source. Official sources must agree exactly; secondary sources
only corroborate or are recorded as disagreements. Values are never averaged or voted on.
Benchmarks need enough samples from enough domains; each domain counts once (its median), outliers outside
1.5 x IQR are dropped, and the spread must stay within the policy ratio.
"""
from datetime import datetime, timezone
from decimal import Decimal, localcontext
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

from app.decision.cost_config import parse_as_of
from app.decision.rates import checks
from app.decision.rates.models import (
    EXCERPT_MAX_CHARS,
    BenchmarkStats,
    Candidate,
    CheckResult,
    Disagreement,
    DomainMedian,
    EvidencePack,
    Proposal,
    ProposalResult,
    RateKind,
    RateRecord,
    ReasonCode,
    RejectionRecord,
    Severity,
    SourceRef,
    SourceRole,
    UnchangedResult,
    derive_id,
    normalise_host,
    pack_hash,
)
from app.decision.rates.policy import Policy, RatePolicy

PRECISION = 28
_ROLE_ORDER = {
    SourceRole.primary: 0,
    SourceRole.agreeing: 1,
    SourceRole.disagreeing: 2,
    SourceRole.sample: 3,
    SourceRole.outlier: 4,
    SourceRole.excluded: 5,
}


class _Prepared(NamedTuple):
    candidate: Candidate
    host: str
    tier: int
    excerpt: str  # capped at EXCERPT_MAX_CHARS; the checks run on this stored text
    truncated: bool
    checks: List[CheckResult]

    @property
    def valid(self) -> bool:
        return all(c.passed for c in self.checks)

    def first_failure(self) -> Optional[CheckResult]:
        return next((c for c in self.checks if not c.passed), None)


def _canonical(c: Candidate) -> Tuple[str, ...]:
    return (c.source_url, c.fetch_id, c.retrieved_at.isoformat(), str(c.value), c.unit, c.effective_date or "", c.excerpt)


def _prepare(
    rate_key: str, candidates: Sequence[Candidate], rp: RatePolicy, now: datetime
) -> Tuple[List[_Prepared], List[_Prepared]]:
    """Candidates for this rate_key (with their checks) and candidates for another key (excluded)."""
    matching, others = [], []
    for c in sorted(candidates, key=_canonical):
        host = normalise_host(c.source_url) or ""
        excerpt = c.excerpt[:EXCERPT_MAX_CHARS]
        truncated = len(c.excerpt) > EXCERPT_MAX_CHARS
        if c.rate_key != rate_key:
            others.append(_Prepared(c, host, 3, excerpt, truncated, [checks.check_rate_key(c, rate_key)]))
            continue
        tier = checks.tier_for(host, c.source_url, rp)
        matching.append(_Prepared(c, host, tier, excerpt, truncated, checks.candidate_checks(c, excerpt, rp, now)))
    return matching, others


def _source_ref(p: _Prepared, role: SourceRole) -> SourceRef:
    c = p.candidate
    return SourceRef(
        url=c.source_url, domain=p.host, tier=p.tier, claimed_tier=c.source_tier, role=role, value=c.value,
        unit=c.unit, effective_date=c.effective_date, retrieved_at=c.retrieved_at, excerpt=p.excerpt,
        excerpt_truncated=p.truncated, snapshot_ref=c.snapshot_ref, fetch_id=c.fetch_id, fixture=c.is_fixture,
    )


def _source_sort(s: SourceRef) -> Tuple:
    return (_ROLE_ORDER[s.role], s.tier, s.domain, s.url, s.fetch_id, s.retrieved_at.isoformat())


def _unique(items: Sequence[str]) -> List[str]:
    return list(dict.fromkeys(items))


def _reject(
    rate_key: str, reason: ReasonCode, name: str, detail: str, results: List[CheckResult],
    prepared: Sequence[_Prepared], now: datetime,
) -> RejectionRecord:
    decisive = CheckResult(name=name, passed=False, severity=Severity.hard, reason_code=reason, detail=detail)
    all_results = list(results) + [decisive]
    codes = _unique([reason] + [r.reason_code for r in results if not r.passed and r.reason_code is not None])
    sources = sorted((_source_ref(p, SourceRole.excluded) for p in prepared), key=_source_sort)
    digest = derive_id("", *(f"{s.url}#{s.fetch_id}#{s.value}" for s in sources))
    return RejectionRecord(
        rejection_id=derive_id("rej_", rate_key, reason.value, digest, now.isoformat()),
        rate_key=rate_key, reason_code=reason, reason_codes=codes, detail=detail, check_results=all_results,
        sources=sources, created_at=now,
    )


def _versus_current(same_value: bool, new_date: str, current: RateRecord) -> str:
    """reconfirmation | unchanged | older | changed (decision 4 in docs/decisions.md section 7)."""
    new, old = parse_as_of(new_date), parse_as_of(current.effective_date)
    if same_value:
        return "reconfirmation" if new > old else "unchanged"
    return "older" if new < old else "changed"


def _change_fields(
    value: Decimal, current: Optional[RateRecord], rp: RatePolicy,
    placeholder_value: Optional[Decimal], placeholder_detail: Optional[str],
) -> Tuple[List[CheckResult], Dict]:
    if current is not None:
        result = checks.check_change(value, current.value, rp)
        fields = {
            "current_value": current.value, "current_effective_date": current.effective_date,
            "current_proposal_id": current.proposal_id, "change_abs": value - current.value,
            "change_pct": checks.change_pct(value, current.value),
        }
        return [result], fields
    results = [CheckResult(
        name="approved_baseline", passed=False, severity=Severity.warning,
        detail="No approved value exists yet, so the change could not be checked against an approved baseline.",
    )]
    fields: Dict = {}
    if placeholder_value is not None:
        pct = checks.change_pct(value, placeholder_value)
        shown = "unbounded (placeholder is 0)" if pct is None else f"{checks.fmt_pct(pct)}%"
        fields = {"placeholder_value": placeholder_value, "placeholder_change_pct": pct,
                  "placeholder_detail": placeholder_detail}
        results.append(CheckResult(
            name="change_vs_placeholder", passed=True, severity=Severity.info,
            detail=f"Information only: YAML placeholder {checks.fmt(placeholder_value)}"
                   f"{' (' + placeholder_detail + ')' if placeholder_detail else ''}; change {shown}.",
        ))
    return results, fields


def _proposal(
    rate_key: str, rp: RatePolicy, now: datetime, roles: Sequence[Tuple[_Prepared, SourceRole]],
    results: List[CheckResult], *, value: Decimal, effective_date: Optional[str], reconfirmation: bool,
    change_fields: Dict, agreeing_domains: int, corroboration: str, disagreements: List[Disagreement],
    benchmark: Optional[BenchmarkStats],
) -> Proposal:
    sources = sorted((_source_ref(p, role) for p, role in roles), key=_source_sort)
    warnings = _unique([f"{r.name}: {r.detail}" for r in results if not r.passed and r.severity is Severity.warning])
    pack = EvidencePack(
        rate_key=rate_key, kind=rp.kind, proposed_value=value, unit=rp.required_unit, effective_date=effective_date,
        reconfirmation=reconfirmation, sources=sources, agreeing_domains=agreeing_domains,
        corroboration=corroboration, disagreements=disagreements, benchmark=benchmark, check_results=results,
        warnings=warnings, fixture_data=any(s.fixture for s in sources), **change_fields,
    )
    pack = pack.model_copy(update={"content_hash": pack_hash(pack)})
    return Proposal(
        proposal_id=derive_id("prop_", rate_key, pack.content_hash, now.isoformat()), rate_key=rate_key,
        kind=rp.kind, evidence_pack=pack, created_at=now,
    )


def _statutory(
    rate_key: str, rp: RatePolicy, prepared: List[_Prepared], others: List[_Prepared],
    current: Optional[RateRecord], now: datetime,
    placeholder_value: Optional[Decimal], placeholder_detail: Optional[str],
) -> ProposalResult:
    results = [r for p in prepared + others for r in p.checks]
    everyone = prepared + others
    tier1 = [p for p in prepared if p.tier == 1]
    if not tier1:
        return _reject(rate_key, ReasonCode.no_authoritative_source, "authoritative_source",
                       "No candidate comes from a tier-1 (official, https) domain listed in the policy.",
                       results, everyone, now)
    official_values = sorted({p.candidate.value for p in tier1})
    if len(official_values) > 1:
        shown = ", ".join(checks.fmt(v) for v in official_values)
        return _reject(rate_key, ReasonCode.conflicting_official_sources, "official_agreement",
                       f"Official sources report different values ({shown}); values are never averaged or voted on.",
                       results, everyone, now)
    valid_t1 = [p for p in tier1 if p.valid]
    if not valid_t1:
        failure = tier1[0].first_failure()
        return _reject(rate_key, failure.reason_code, "official_source_valid",
                       f"No official source passed every check; first failure ({failure.name}): {failure.detail}",
                       results, everyone, now)

    primary = sorted(valid_t1, key=lambda p: (-parse_as_of(p.candidate.effective_date).toordinal(),
                                              p.candidate.source_url, p.candidate.fetch_id))[0]
    value, effective_date = primary.candidate.value, primary.candidate.effective_date
    reconfirmation = False
    if current is not None:
        state = _versus_current(value == current.value, effective_date, current)
        if state == "unchanged":
            return UnchangedResult(
                rate_key=rate_key, value=value, effective_date=effective_date,
                current_proposal_id=current.proposal_id,
                detail=f"Same value as the approved record ({checks.fmt(value)}); effective date {effective_date} "
                       f"is not newer than {current.effective_date}.",
            )
        if state == "older":
            return _reject(rate_key, ReasonCode.older_than_current, "effective_date_order",
                           f"Effective date {effective_date} is older than the approved record's "
                           f"{current.effective_date}, with a different value.", results, everyone, now)
        reconfirmation = state == "reconfirmation"

    roles: List[Tuple[_Prepared, SourceRole]] = []
    agreeing: set = set()
    disagreements: List[Disagreement] = []
    for p in prepared:
        url = p.candidate.source_url
        if p is primary:
            role = SourceRole.primary
        elif not p.valid:
            role = SourceRole.excluded
            if p.tier == 1:
                failure = p.first_failure()
                results.append(CheckResult(
                    name="official_source_excluded", passed=False, severity=Severity.warning, subject=url,
                    detail=f"Official source {p.host} excluded: {failure.name} failed ({failure.detail})",
                ))
        elif p.tier == 1:
            role = SourceRole.agreeing  # official values already agree exactly
        elif p.candidate.value == value:
            role = SourceRole.agreeing
            if not checks.is_official_domain(p.host, rp):
                agreeing.add(checks.domain_key(p.host))
        else:
            role = SourceRole.disagreeing
            detail = (f"Tier {p.tier} source {p.host} reports {checks.fmt(p.candidate.value)}; the official value is "
                      f"{checks.fmt(value)}. Recorded, not averaged.")
            disagreements.append(Disagreement(url=url, domain=p.host, tier=p.tier, value=p.candidate.value,
                                              proposed_value=value, detail=detail))
            results.append(CheckResult(name="secondary_agreement", passed=False, severity=Severity.warning,
                                       subject=url, detail=detail))
        roles.append((p, role))
        if p.candidate.source_tier < p.tier:
            results.append(CheckResult(
                name="source_tier_claim", passed=False, severity=Severity.warning, subject=url,
                detail=f"The fetcher claimed tier {p.candidate.source_tier} for {p.host}; the policy assigns tier {p.tier}.",
            ))
    roles.extend((o, SourceRole.excluded) for o in others)

    results.append(CheckResult(
        name="corroboration", passed=True, severity=Severity.info,
        detail=f"{len(agreeing)} independent tier-2/3 domain(s) agree with the official value.",
    ))
    if reconfirmation:
        results.append(CheckResult(
            name="reconfirmation", passed=True, severity=Severity.info,
            detail=f"Same value as the approved record; newer effective date {effective_date} "
                   f"(approved record: {current.effective_date}).",
        ))
    change_results, change_fields = _change_fields(value, current, rp, placeholder_value, placeholder_detail)
    results.extend(change_results)
    return _proposal(
        rate_key, rp, now, roles, results, value=value, effective_date=effective_date,
        reconfirmation=reconfirmation, change_fields=change_fields, agreeing_domains=len(agreeing),
        corroboration="corroborated" if agreeing else "official_only", disagreements=disagreements, benchmark=None,
    )


def _benchmark(
    rate_key: str, rp: RatePolicy, prepared: List[_Prepared], others: List[_Prepared],
    current: Optional[RateRecord], now: datetime,
    placeholder_value: Optional[Decimal], placeholder_detail: Optional[str],
) -> ProposalResult:
    results = [r for p in prepared + others for r in p.checks]
    everyone = prepared + others
    valid = [p for p in prepared if p.valid]
    if len(valid) < rp.min_samples:
        return _reject(rate_key, ReasonCode.insufficient_samples, "benchmark_samples",
                       f"{len(valid)} valid sample(s); the policy requires at least {rp.min_samples}.",
                       results, everyone, now)

    groups: Dict[str, List[Decimal]] = {}
    for p in valid:
        groups.setdefault(checks.domain_key(p.host), []).append(p.candidate.value)
    points = [(host, checks.median(values)) for host, values in sorted(groups.items())]
    kept, outliers = checks.split_outliers(points)
    if len(kept) < rp.min_distinct_domains:
        return _reject(rate_key, ReasonCode.insufficient_domains, "benchmark_domains",
                       f"{len(kept)} distinct domain(s) after outlier removal; the policy requires at least "
                       f"{rp.min_distinct_domains}.", results, everyone, now)
    kept_values = [v for _, v in kept]
    low, high, mid = min(kept_values), max(kept_values), checks.median(kept_values)
    spread_result, ratio = checks.check_spread(low, high, rp)
    if not spread_result.passed:
        return _reject(rate_key, ReasonCode.spread_too_wide, "benchmark_spread", spread_result.detail,
                       results, everyone, now)
    results.append(spread_result)

    kept_hosts = {host for host, _ in kept}
    used = [p for p in valid if checks.domain_key(p.host) in kept_hosts]
    effective_date = max(p.candidate.retrieved_at.astimezone(timezone.utc).date() for p in used).isoformat()
    stats = BenchmarkStats(
        low=low, median=mid, high=high, sample_count=len(used), raw_sample_count=len(valid),
        domain_count=len(kept), domains=sorted(kept_hosts),
        domain_medians=[DomainMedian(domain=h, median=v, samples=len(groups[h])) for h, v in points],
        outlier_domains=sorted(h for h, _ in outliers), spread_ratio=ratio,
    )
    results.append(CheckResult(
        name="domain_influence_cap", passed=True, severity=Severity.info,
        detail=f"Each domain counts once (the median of its samples): {len(valid)} samples from {len(points)} domains.",
    ))
    results.append(CheckResult(
        name="outliers", passed=True, severity=Severity.info,
        detail=("Removed outside 1.5 x IQR: " + ", ".join(f"{h} ({checks.fmt(v)})" for h, v in outliers))
        if outliers else "No domain outside 1.5 x IQR.",
    ))

    reconfirmation = False
    if current is not None:
        same = (low, mid, high) == (current.range_low, current.value, current.range_high)
        state = _versus_current(same, effective_date, current)
        if state == "unchanged":
            return UnchangedResult(
                rate_key=rate_key, value=mid, effective_date=effective_date, current_proposal_id=current.proposal_id,
                detail=f"Same benchmark as the approved record (low {checks.fmt(low)}, median {checks.fmt(mid)}, "
                       f"high {checks.fmt(high)}); {effective_date} is not newer than {current.effective_date}.",
            )
        if state == "older":
            return _reject(rate_key, ReasonCode.older_than_current, "effective_date_order",
                           f"Benchmark date {effective_date} is older than the approved record's "
                           f"{current.effective_date}, with a different value.", results, everyone, now)
        reconfirmation = state == "reconfirmation"
        if reconfirmation:
            results.append(CheckResult(
                name="reconfirmation", passed=True, severity=Severity.info,
                detail=f"Same benchmark as the approved record; newer date {effective_date} "
                       f"(approved record: {current.effective_date}).",
            ))

    outlier_hosts = {host for host, _ in outliers}
    roles: List[Tuple[_Prepared, SourceRole]] = []
    for p in prepared:
        if not p.valid:
            roles.append((p, SourceRole.excluded))
        elif checks.domain_key(p.host) in outlier_hosts:
            roles.append((p, SourceRole.outlier))
        else:
            roles.append((p, SourceRole.sample))
    roles.extend((o, SourceRole.excluded) for o in others)
    change_results, change_fields = _change_fields(mid, current, rp, placeholder_value, placeholder_detail)
    results.extend(change_results)
    return _proposal(
        rate_key, rp, now, roles, results, value=mid, effective_date=effective_date,
        reconfirmation=reconfirmation, change_fields=change_fields, agreeing_domains=0,
        corroboration="not_applicable", disagreements=[], benchmark=stats,
    )


def build_proposal(
    rate_key: str,
    candidates: Sequence[Candidate],
    current: Optional[RateRecord],
    policy: Policy,
    now: datetime,
    placeholder_value: Optional[Decimal] = None,
    placeholder_detail: Optional[str] = None,
) -> ProposalResult:
    """Build a Proposal, RejectionRecord or UnchangedResult. `now` is supplied by the caller (timezone-aware).

    placeholder_value / placeholder_detail are shown as information only when there is no approved baseline.
    """
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")
    rp = policy.rates.get(rate_key)
    if rp is None:
        raise KeyError(f"no policy for rate_key {rate_key!r}")
    if current is not None and current.rate_key != rate_key:
        raise ValueError(f"current record is for {current.rate_key}, not {rate_key}")
    if any(not isinstance(c, Candidate) for c in candidates):
        raise TypeError("candidates must be Candidate instances")
    if placeholder_value is not None and isinstance(placeholder_value, (float, bool)):
        raise TypeError("placeholder_value must be a Decimal")
    with localcontext() as ctx:
        ctx.prec = PRECISION
        prepared, others = _prepare(rate_key, candidates, rp, now)
        if rp.kind is RateKind.statutory:
            return _statutory(rate_key, rp, prepared, others, current, now, placeholder_value, placeholder_detail)
        return _benchmark(rate_key, rp, prepared, others, current, now, placeholder_value, placeholder_detail)
