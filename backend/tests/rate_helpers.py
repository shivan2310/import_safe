"""Shared fixtures for the rate pipeline tests (not a test module). All URLs are test fixtures."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Sequence

from app.decision.cost_config import load_cost_assumptions
from app.decision.rates import review
from app.decision.rates.builder import build_proposal
from app.decision.rates.models import Candidate, Proposal, ProposalCreated, RateKind, RateRecord, config_fields
from app.decision.rates.policy import Policy, load_policy
from app.decision.rates.store import RateStore

D = Decimal
NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
POLICY = load_policy()

OFFICIAL_URL = {
    "fx_usd_inr": "https://www.cbic.gov.in/test-fixture/exchange-rates.pdf",
    "bcd_pct": "https://www.cbic.gov.in/test-fixture/tariff-chapter-85.pdf",
    "sws_pct_of_bcd": "https://egazette.gov.in/test-fixture/sws.pdf",
    "igst_pct": "https://cbic-gst.gov.in/test-fixture/igst-rates.html",
}
EXCERPT = {
    "fx_usd_inr": "Schedule I, imported goods: 1 United States Dollar (USD) = {v} Indian Rupees",
    "bcd_pct": "Heading 8518 22 00: basic customs duty {v}% ad valorem",
    "sws_pct_of_bcd": "Social Welfare Surcharge at the rate of {v} per cent of the aggregate duties of customs",
    "igst_pct": "Integrated tax on goods of heading 8518: {v} percent",
}
UNIT = {"fx_usd_inr": "inr_per_usd", "bcd_pct": "percent", "sws_pct_of_bcd": "percent", "igst_pct": "percent"}
# Placeholder values in cost_assumptions.yaml, read once (the tests never write the YAML).
YAML_VALUES: Dict[str, Decimal] = {name: getattr(load_cost_assumptions(), name).value for name in config_fields()}


def statutory(
    rate_key: str = "fx_usd_inr", value: str = "84.50", url: Optional[str] = None, tier: int = 1,
    excerpt: Optional[str] = None, effective_date: Optional[str] = "2026-10-23", unit: Optional[str] = None,
    fetch_id: str = "f-1", retrieved_at: datetime = NOW, kind: str = "statutory", snapshot_ref: Optional[str] = None,
) -> Candidate:
    return Candidate(
        rate_key=rate_key, kind=kind, value=D(value), unit=unit or UNIT.get(rate_key, "percent"),
        effective_date=effective_date, source_url=url or OFFICIAL_URL[rate_key], source_tier=tier,
        excerpt=excerpt if excerpt is not None else EXCERPT[rate_key].format(v=value),
        snapshot_ref=snapshot_ref, retrieved_at=retrieved_at, fetch_id=fetch_id,
    )


def sample(
    rate_key: str = "clearing_inr", value: str = "3000", domain: str = "site-0.example", index: int = 0,
    retrieved_at: datetime = NOW, unit: str = "inr_per_shipment", excerpt: Optional[str] = None,
) -> Candidate:
    amount = D(value)
    return Candidate(
        rate_key=rate_key, kind="benchmark", value=amount, unit=unit,
        source_url=f"https://{domain}/test-fixture/{rate_key}/{index}", source_tier=3,
        excerpt=excerpt if excerpt is not None else f"Typical charge: Rs {amount:,} per shipment",
        retrieved_at=retrieved_at, fetch_id=f"s-{domain}-{index}",
    )


def samples(rate_key: str, values: Sequence[str], domains: Optional[Sequence[str]] = None,
            retrieved_at: datetime = NOW) -> List[Candidate]:
    domains = list(domains) if domains is not None else [f"site-{i}.example" for i in range(len(values))]
    return [sample(rate_key, v, d, i, retrieved_at) for i, (v, d) in enumerate(zip(values, domains))]


def policy_with(key: Optional[str] = None, base: Optional[Policy] = None, **changes) -> Policy:
    """A validated copy of the policy with one rate entry (or, with key=None, the top level) changed."""
    raw = (base or POLICY).model_dump()
    if key is None:
        raw.update(changes)
    else:
        raw["rates"][key].update(changes)
    return Policy.model_validate(raw)


def record(rate_key: str = "fx_usd_inr", value: str = "84.50", effective_date: str = "2026-10-23",
           kind: RateKind = RateKind.statutory, **extra) -> RateRecord:
    fields = dict(
        rate_key=rate_key, kind=kind, evidence_kind="official" if kind is RateKind.statutory else "benchmark",
        value=D(value), unit=UNIT.get(rate_key, "inr_per_shipment"), effective_date=effective_date,
        source=OFFICIAL_URL.get(rate_key, "market benchmark"), proposal_id="prop_existing",
        approved_by="Reviewer A", approved_at=NOW, evidence_hash="sha256:existing",
    )
    fields.update(extra)
    return RateRecord(**fields)


def make_store(tmp_path, name: str = "events.jsonl") -> RateStore:
    return RateStore(tmp_path / name)


def propose(store: RateStore, policy: Policy, rate_key: str, candidates: Sequence[Candidate],
            now: datetime = NOW, placeholder: Optional[Decimal] = None) -> Proposal:
    result = build_proposal(rate_key, candidates, store.latest_approved(rate_key), policy, now, placeholder)
    assert isinstance(result, Proposal), result
    store.append_event(ProposalCreated(proposal=result))
    return result


def approve(store: RateStore, policy: Policy, proposal: Proposal, now: datetime = NOW, by: str = "Reviewer A",
            allow_fixture: bool = False):
    return review.approve(store, policy, proposal.proposal_id, by, now,
                          note="Checked the official excerpt.", acknowledge_warnings=True, allow_fixture=allow_fixture)


def propose_and_approve(store: RateStore, policy: Policy, rate_key: str, candidates: Sequence[Candidate],
                        now: datetime = NOW) -> Proposal:
    proposal = propose(store, policy, rate_key, candidates, now)
    approve(store, policy, proposal, now)
    return proposal


# ---- a policy covering every config entry (for the rates_verified tests) ------------------------

TEST_OFFICIAL = "official-rates.example"


def full_policy() -> Policy:
    raw = POLICY.model_dump()
    rates = {k: v for k, v in raw["rates"].items() if k in ("fx_usd_inr", "bcd_pct", "sws_pct_of_bcd", "igst_pct",
                                                            "default_freight_inr")}
    for name in config_fields():
        if name in rates or name in ("default_freight_low_inr", "default_freight_high_inr"):
            continue
        percent = "_pct" in name
        rates[name] = {
            "kind": "statutory", "required_unit": "percent" if percent else "inr",
            "min_value": D(0), "max_value": D(100) if percent else D(1000000), "max_change_pct": D(50),
            "tier1_domains": [TEST_OFFICIAL],
        }
    raw["rates"] = rates
    return Policy.model_validate(raw)


def full_candidates(rate_key: str, value: Decimal) -> List[Candidate]:
    """One official candidate for a config entry, with the YAML value."""
    text = format(value, "f")
    if rate_key in OFFICIAL_URL:
        return [statutory(rate_key, text)]
    percent = "_pct" in rate_key
    return [Candidate(
        rate_key=rate_key, kind="statutory", value=value, unit="percent" if percent else "inr",
        effective_date="2026-10-23", source_url=f"https://{TEST_OFFICIAL}/test-fixture/{rate_key}",
        source_tier=1, excerpt=f"{rate_key}: {text}%" if percent else f"{rate_key}: Rs {text} per shipment",
        retrieved_at=NOW, fetch_id=f"full-{rate_key}",
    )]


def approve_everything(store: RateStore, policy: Policy, skip: Sequence[str] = ()) -> None:
    for key in policy.rates:
        if key in skip:
            continue
        if key == "default_freight_inr":
            cands = samples(key, ["10000", "11000", "12000", "13000", "14000"])
        else:
            cands = full_candidates(key, YAML_VALUES[key])
        propose_and_approve(store, policy, key, cands)


def later(hours: int = 0, days: int = 0) -> datetime:
    return NOW + timedelta(hours=hours, days=days)
