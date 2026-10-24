"""Pure checks for rate candidates. No clock, network or file access: every input is passed in.

Each function returns a CheckResult. The builder decides what a failure means for the whole set: reject it
(hard), flag the proposal (warning), or only exclude one source (info).
"""
import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import List, Optional, Sequence, Tuple

from app.decision.cost_config import parse_as_of
from app.decision.rates.models import Candidate, CheckResult, RateKind, ReasonCode, Severity, url_scheme
from app.decision.rates.policy import RatePolicy

_NUMBER = re.compile(r"[0-9][0-9,]*(?:\.[0-9]+)?")
_PERCENT_AFTER = re.compile(r"\s*(?:%|per[\s-]?cent\b)", re.IGNORECASE)
_HUNDRED = Decimal(100)
_TWO = Decimal(2)
IQR_FACTOR = Decimal("1.5")  # Tukey fences: outside Q1 - 1.5 x IQR or Q3 + 1.5 x IQR is an outlier
_Q1 = Decimal("0.25")
_Q3 = Decimal("0.75")


def fmt(value: Decimal) -> str:
    """Plain (non-scientific) text for a Decimal."""
    return format(value, "f")


def fmt_pct(value: Decimal) -> str:
    """Two decimals, ROUND_HALF_UP (explicit, so display never depends on the global Decimal context)."""
    return format(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), "f")


# ---- tiers -------------------------------------------------------------------------------------

def _listed(host: str, domains: Sequence[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def domain_key(host: str) -> str:
    """Host used for counting distinct domains: a leading 'www.' does not make a second independent site."""
    return host[4:] if host.startswith("www.") else host


def is_official_domain(host: str, rp: RatePolicy) -> bool:
    return _listed(host, rp.tier1_domains)


def tier_for(host: str, url: str, rp: RatePolicy) -> int:
    """Tier from the policy lists only. Tier 1 also requires https. A domain in neither list is tier 3."""
    if _listed(host, rp.tier1_domains) and url_scheme(url) == "https":
        return 1
    if _listed(host, rp.tier2_domains):
        return 2
    return 3


# ---- per-candidate checks ----------------------------------------------------------------------

def check_rate_key(candidate: Candidate, rate_key: str) -> CheckResult:
    passed = candidate.rate_key == rate_key
    return CheckResult(
        name="rate_key", passed=passed, subject=candidate.source_url,
        reason_code=None if passed else ReasonCode.rate_key_mismatch,
        detail=f"Candidate is for {candidate.rate_key}; expected {rate_key}.",
    )


def check_kind(candidate: Candidate, rp: RatePolicy) -> CheckResult:
    passed = candidate.kind is rp.kind
    return CheckResult(
        name="kind", passed=passed, subject=candidate.source_url,
        reason_code=None if passed else ReasonCode.kind_mismatch,
        detail=f"Candidate kind {candidate.kind.value}; policy expects {rp.kind.value}.",
    )


def check_unit(candidate: Candidate, rp: RatePolicy) -> CheckResult:
    unit = candidate.unit.strip().lower()
    passed = unit == rp.required_unit
    return CheckResult(
        name="unit", passed=passed, subject=candidate.source_url,
        reason_code=None if passed else ReasonCode.unit_mismatch,
        detail=f"Unit {candidate.unit!r}; policy requires {rp.required_unit!r}.",
    )


def check_bounds(candidate: Candidate, rp: RatePolicy) -> CheckResult:
    passed = rp.min_value <= candidate.value <= rp.max_value
    return CheckResult(
        name="bounds", passed=passed, subject=candidate.source_url,
        reason_code=None if passed else ReasonCode.out_of_bounds,
        detail=f"Value {fmt(candidate.value)}; allowed range {fmt(rp.min_value)} to {fmt(rp.max_value)}.",
    )


def numbers_in(text: str) -> List[Tuple[Decimal, int]]:
    """Numeric tokens in the text with the index just after each token. Thousands separators are removed and
    values compare numerically, so 84.50 equals 84.5 and 1,00,000 equals 100000."""
    found = []
    for match in _NUMBER.finditer(text):
        token = match.group(0).rstrip(",")
        digits = token.replace(",", "")
        try:
            found.append((Decimal(digits), match.start() + len(token)))
        except InvalidOperation:
            continue
    return found


def _names_currency(excerpt: str, terms: Sequence[str]) -> bool:
    return any(
        re.search(r"(?<![A-Za-z])" + re.escape(term) + r"(?![A-Za-z])", excerpt, re.IGNORECASE) for term in terms
    )


def check_number_in_excerpt(value: Decimal, excerpt: str, rp: RatePolicy, subject: Optional[str] = None) -> CheckResult:
    """The value must appear as a number in the excerpt. Percent units also need %, 'per cent' or 'percent'
    right after the number; rates with currency_terms also need the currency named in the excerpt."""

    def result(passed: bool, detail: str) -> CheckResult:
        return CheckResult(
            name="number_in_excerpt", passed=passed, subject=subject, detail=detail,
            reason_code=None if passed else ReasonCode.number_not_in_excerpt,
        )

    ends = [end for number, end in numbers_in(excerpt) if number == value]
    if not ends:
        return result(False, f"The value {fmt(value)} does not appear as a number in the excerpt.")
    if rp.required_unit == "percent" and not any(_PERCENT_AFTER.match(excerpt, end) for end in ends):
        return result(False, f"The value {fmt(value)} appears, but not followed by %, 'per cent' or 'percent'.")
    if rp.currency_terms and not _names_currency(excerpt, rp.currency_terms):
        return result(False, f"The excerpt does not name the currency ({', '.join(rp.currency_terms)}).")
    return result(True, f"The value {fmt(value)} appears in the excerpt.")


def check_effective_date(
    effective_date: Optional[str], rp: RatePolicy, now: datetime, subject: Optional[str] = None
) -> CheckResult:
    """Parseable ISO date, not further ahead of now than the policy allows. Optional for benchmarks."""

    def result(passed: bool, detail: str) -> CheckResult:
        return CheckResult(
            name="effective_date", passed=passed, subject=subject, detail=detail,
            reason_code=None if passed else ReasonCode.bad_effective_date,
        )

    if effective_date is None:
        if rp.kind is RateKind.benchmark:
            return result(True, "No effective date given; not required for benchmarks.")
        return result(False, "No effective date given; statutory rates need one.")
    try:
        parsed = parse_as_of(effective_date)
    except ValueError as exc:
        return result(False, str(exc))
    ahead = (parsed - now.date()).days
    if ahead > rp.max_effective_date_future_days:
        return result(
            False, f"Effective date {effective_date} is {ahead} days ahead; at most "
                   f"{rp.max_effective_date_future_days} allowed.",
        )
    return result(True, f"Effective date {effective_date}.")


def candidate_checks(candidate: Candidate, excerpt: str, rp: RatePolicy, now: datetime) -> List[CheckResult]:
    """Per-candidate checks in fixed order: kind, unit, bounds, number in excerpt, effective date."""
    return [
        check_kind(candidate, rp),
        check_unit(candidate, rp),
        check_bounds(candidate, rp),
        check_number_in_excerpt(candidate.value, excerpt, rp, subject=candidate.source_url),
        check_effective_date(candidate.effective_date, rp, now, subject=candidate.source_url),
    ]


# ---- change ------------------------------------------------------------------------------------

def change_pct(new: Decimal, old: Decimal) -> Optional[Decimal]:
    """Absolute change in percent of the old value; None when old is 0 and new is not (unbounded change)."""
    if old == 0:
        return Decimal(0) if new == 0 else None
    return abs(new - old) / old * _HUNDRED


def check_change(new: Decimal, current: Decimal, rp: RatePolicy) -> CheckResult:
    pct = change_pct(new, current)
    passed = pct is not None and pct <= rp.max_change_pct
    shown = "unbounded (approved value is 0)" if pct is None else f"{fmt_pct(pct)}%"
    return CheckResult(
        name="change_within_limit", passed=passed, severity=Severity.warning,
        detail=f"Change from approved {fmt(current)} to {fmt(new)} is {shown}; limit {fmt(rp.max_change_pct)}%.",
    )


# ---- benchmarks --------------------------------------------------------------------------------

def median(values: Sequence[Decimal]) -> Decimal:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("median of an empty list")
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / _TWO


def quantile(ordered: Sequence[Decimal], q: Decimal) -> Decimal:
    """Linear interpolation between closest ranks (the 'inclusive' method)."""
    if not ordered:
        raise ValueError("quantile of an empty list")
    position = (len(ordered) - 1) * q
    lower = int(position)
    fraction = position - lower
    if lower + 1 >= len(ordered):
        return ordered[lower]
    return ordered[lower] + (ordered[lower + 1] - ordered[lower]) * fraction


def split_outliers(points: Sequence[Tuple[str, Decimal]]) -> Tuple[List[Tuple[str, Decimal]], List[Tuple[str, Decimal]]]:
    """Split (domain, value) points into kept and outliers using Tukey fences on the values."""
    ordered = sorted(value for _, value in points)
    q1, q3 = quantile(ordered, _Q1), quantile(ordered, _Q3)
    spread = q3 - q1
    low_fence, high_fence = q1 - IQR_FACTOR * spread, q3 + IQR_FACTOR * spread
    kept = [p for p in points if low_fence <= p[1] <= high_fence]
    outliers = [p for p in points if not (low_fence <= p[1] <= high_fence)]
    return kept, outliers


def check_spread(low: Decimal, high: Decimal, rp: RatePolicy) -> Tuple[CheckResult, Optional[Decimal]]:
    """Spread is high / low; it must not exceed max_spread_ratio."""
    if low == 0:
        ratio = Decimal(1) if high == 0 else None
    else:
        ratio = high / low
    passed = ratio is not None and ratio <= rp.max_spread_ratio
    shown = "unbounded (low is 0)" if ratio is None else fmt_pct(ratio)
    result = CheckResult(
        name="benchmark_spread", passed=passed, severity=Severity.hard if not passed else Severity.info,
        reason_code=None if passed else ReasonCode.spread_too_wide,
        detail=f"Spread high/low is {shown}; limit {fmt(rp.max_spread_ratio)}.",
    )
    return result, ratio
