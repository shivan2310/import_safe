from decimal import Decimal as D

import pytest

from app.decision.rates.fetcher import FixtureFetcher, RateFetcher
from app.decision.rates.models import ProposalStatus, ReasonCode
from app.decision.rates.store import StoreCorruptionError
from app.decision.rates.updater import RefreshOutcome, refresh_rates
from tests.rate_helpers import NOW, POLICY, approve, later, make_store, policy_with, samples, statutory


def outcomes(report):
    return {r.rate_key: r.outcome for r in report.results}


def test_fixture_fetcher_satisfies_the_protocol():
    assert isinstance(FixtureFetcher({}), RateFetcher)


def test_refresh_creates_pending_proposal(tmp_path):
    store = make_store(tmp_path)
    report = refresh_rates(["fx_usd_inr"], FixtureFetcher({"fx_usd_inr": [statutory()]}), POLICY, store, NOW)
    (result,) = report.results
    assert result.outcome is RefreshOutcome.created
    proposal = store.get_proposal(result.proposal_id)
    assert proposal.status is ProposalStatus.pending
    assert proposal.evidence_pack.placeholder_value == D("90")  # YAML placeholder shown as information
    assert report.runs_used == 1 and report.domains_used == ["www.cbic.gov.in"]
    assert store.latest_approved("fx_usd_inr") is None  # nothing is applied without approval


def test_benchmark_placeholder_for_default_freight_is_the_midpoint(tmp_path):
    store = make_store(tmp_path)
    cands = samples("default_freight_inr", ["10000", "11000", "12000", "13000", "14000"])
    report = refresh_rates(["default_freight_inr"], FixtureFetcher({"default_freight_inr": cands}), POLICY, store, NOW)
    pack = store.get_proposal(report.results[0].proposal_id).evidence_pack
    assert pack.placeholder_value == D(12500)
    assert "5000 to 20000" in pack.placeholder_detail


def test_unchanged_value_creates_no_proposal(tmp_path):
    store = make_store(tmp_path)
    fetcher = FixtureFetcher({"fx_usd_inr": [statutory()]})
    first = refresh_rates(["fx_usd_inr"], fetcher, POLICY, store, NOW)
    approve(store, POLICY, store.get_proposal(first.results[0].proposal_id), allow_fixture=True)
    before = store.path.read_bytes()
    second = refresh_rates(["fx_usd_inr"], fetcher, POLICY, store, later(hours=1))
    assert second.results[0].outcome is RefreshOutcome.unchanged
    assert store.path.read_bytes() == before


def test_same_value_newer_date_is_a_reconfirmation(tmp_path):
    store = make_store(tmp_path)
    first = refresh_rates(["fx_usd_inr"], FixtureFetcher({"fx_usd_inr": [statutory()]}), POLICY, store, NOW)
    approve(store, POLICY, store.get_proposal(first.results[0].proposal_id), allow_fixture=True)
    newer =FixtureFetcher({"fx_usd_inr": [statutory(effective_date="2026-11-06")]})
    report = refresh_rates(["fx_usd_inr"], newer, POLICY, store, later(days=13))
    assert report.results[0].outcome is RefreshOutcome.reconfirmation
    assert store.get_proposal(report.results[0].proposal_id).evidence_pack.reconfirmation


def test_new_pending_proposal_supersedes_the_older_one(tmp_path):
    store = make_store(tmp_path)
    first = refresh_rates(["fx_usd_inr"], FixtureFetcher({"fx_usd_inr": [statutory()]}), POLICY, store, NOW)
    old_id = first.results[0].proposal_id
    newer = FixtureFetcher({"fx_usd_inr": [statutory(value="84.60", excerpt="1 USD = 84.60 INR")]})
    second = refresh_rates(["fx_usd_inr"], newer, POLICY, store, later(hours=1))
    new_id = second.results[0].proposal_id
    assert second.results[0].superseded == [old_id]
    assert store.get_proposal(old_id).status is ProposalStatus.superseded
    assert store.get_proposal(new_id).status is ProposalStatus.pending
    assert [p.proposal_id for p in store.proposals(ProposalStatus.pending)] == [new_id]


def test_rejection_is_logged_not_proposed(tmp_path):
    store = make_store(tmp_path)
    fetcher = FixtureFetcher({"fx_usd_inr": [statutory(url="https://news.example/fx")]})
    report = refresh_rates(["fx_usd_inr"], fetcher, POLICY, store, NOW)
    (result,) = report.results
    assert result.outcome is RefreshOutcome.rejected
    assert result.reason_code is ReasonCode.no_authoritative_source
    assert store.proposals() == []
    (rejection,) = store.rejections("fx_usd_inr")
    assert rejection.rejection_id == result.rejection_id


def test_fetch_error_is_recorded_and_refresh_continues(tmp_path):
    store = make_store(tmp_path)
    fetcher = FixtureFetcher({"fx_usd_inr": [statutory()]}, errors={"bcd_pct": TimeoutError("portal timed out")})
    report = refresh_rates(["bcd_pct", "fx_usd_inr"], fetcher, POLICY, store, NOW)
    assert outcomes(report) == {"bcd_pct": RefreshOutcome.fetch_error, "fx_usd_inr": RefreshOutcome.created}
    bcd = report.results[0]
    assert bcd.reason_code is ReasonCode.fetch_error and "TimeoutError" in bcd.detail
    (logged,) = store.rejections("bcd_pct")
    assert logged.reason_code is ReasonCode.fetch_error


class _BadFetcher:
    def fetch(self, rate_key):
        return {"value": 84.5}


def test_fetcher_returning_the_wrong_type_is_a_fetch_error(tmp_path):
    store = make_store(tmp_path)
    report = refresh_rates(["fx_usd_inr"], _BadFetcher(), POLICY, store, NOW)
    assert report.results[0].outcome is RefreshOutcome.fetch_error


def test_run_budget_stops_the_refresh(tmp_path):
    store = make_store(tmp_path)
    policy = policy_with(max_runs_per_refresh=1)
    fetcher = FixtureFetcher({"fx_usd_inr": [statutory()], "bcd_pct": [statutory("bcd_pct", "20")]})
    report = refresh_rates(["fx_usd_inr", "bcd_pct", "igst_pct"], fetcher, policy, store, NOW)
    assert outcomes(report) == {"fx_usd_inr": RefreshOutcome.created, "bcd_pct": RefreshOutcome.budget_exhausted,
                                "igst_pct": RefreshOutcome.budget_exhausted}
    assert report.budget_exhausted is True
    assert fetcher.calls == ["fx_usd_inr"]


def test_domain_budget_stops_the_refresh(tmp_path):
    store = make_store(tmp_path)
    policy = policy_with(max_domains_per_refresh=3)
    cands = samples("clearing_inr", ["3000", "3200", "3400", "3600", "12000"])  # five domains
    fetcher = FixtureFetcher({"clearing_inr": cands, "fx_usd_inr": [statutory()]})
    report = refresh_rates(["clearing_inr", "fx_usd_inr"], policy=policy, fetcher=fetcher, store=store, now=NOW)
    assert outcomes(report) == {"clearing_inr": RefreshOutcome.created, "fx_usd_inr": RefreshOutcome.budget_exhausted}
    assert report.budget_exhausted is True and len(report.domains_used) == 5


def test_unknown_rate_key_is_not_fetched(tmp_path):
    store = make_store(tmp_path)
    fetcher = FixtureFetcher({})
    report = refresh_rates(["landing_charge_pct"], fetcher, POLICY, store, NOW)
    assert report.results[0].outcome is RefreshOutcome.unknown_rate_key
    assert fetcher.calls == [] and report.runs_used == 0


def test_identical_rerun_at_the_same_time_is_not_duplicated(tmp_path):
    store = make_store(tmp_path)
    fetcher = FixtureFetcher({"fx_usd_inr": [statutory()]})
    refresh_rates(["fx_usd_inr"], fetcher, POLICY, store, NOW)
    again = refresh_rates(["fx_usd_inr"], fetcher, POLICY, store, NOW)
    assert again.results[0].outcome is RefreshOutcome.already_recorded
    assert len(store.proposals()) == 1


def test_corrupt_store_is_not_swallowed(tmp_path):
    store = make_store(tmp_path)
    refresh_rates(["fx_usd_inr"], FixtureFetcher({"fx_usd_inr": [statutory()]}), POLICY, store, NOW)
    store.path.write_bytes(b"garbage\n" + store.path.read_bytes())
    with pytest.raises(StoreCorruptionError):
        refresh_rates(["fx_usd_inr"], FixtureFetcher({"fx_usd_inr": [statutory()]}), POLICY, store, later(hours=1))


def test_naive_now_rejected(tmp_path):
    from datetime import datetime
    with pytest.raises(ValueError):
        refresh_rates(["fx_usd_inr"], FixtureFetcher({}), POLICY, make_store(tmp_path), datetime(2026, 10, 24))


def test_report_has_no_forbidden_words(tmp_path):
    store = make_store(tmp_path)
    fetcher = FixtureFetcher({"fx_usd_inr": [statutory()], "igst_pct": [statutory("igst_pct", "18", excerpt="18")]},
                             errors={"bcd_pct": RuntimeError("blocked")})
    text = refresh_rates(["fx_usd_inr", "bcd_pct", "igst_pct"], fetcher, POLICY, store, NOW).model_dump_json().lower()
    assert "fraud" not in text and "fake" not in text
