from datetime import datetime, timedelta, timezone
from decimal import Decimal as D

import pytest
from pydantic import ValidationError

from app.decision.cost_config import load_cost_assumptions
from app.decision.cost_engine import CostInputs, estimate_cost
from app.decision.rates import review
from app.decision.rates.fetcher import FixtureFetcher
from app.decision.rates.loader import FIXTURE_LABEL, RateLoaderWarning, load_assumptions_report, load_assumptions_with_store
from app.decision.rates.models import Candidate, ProposalStatus
from app.decision.rates.review import ReviewError, approve, main, render_proposal
from app.decision.rates.updater import refresh_rates
from tests.rate_helpers import NOW, POLICY, later, make_store, propose, propose_and_approve, statutory

NOTE = "Checked the official excerpt."
FALLBACK = "latest approval ignored (evidence hash mismatch); using the approval from 2026-10-24"


def golden_inputs():
    return CostInputs(unit_price=D("10"), price_currency="USD", quantity=100, freight_inr=D("12000"),
                      insurance_inr=D("0"))


def fixture_proposal(store, now=NOW, effective_date="2026-10-23"):
    fetcher = FixtureFetcher({"fx_usd_inr": [statutory(effective_date=effective_date, retrieved_at=now)]})
    report = refresh_rates(["fx_usd_inr"], fetcher, POLICY, store, now)
    return store.get_proposal(report.results[0].proposal_id)


# ---- fallback to the previous approval ---------------------------------------------------------

def _two_approvals_latest_tampered(tmp_path):
    store = make_store(tmp_path)
    propose_and_approve(store, POLICY, "fx_usd_inr", [statutory()])  # approved 2026-10-24
    newer = propose(store, POLICY, "fx_usd_inr",
                    [statutory(value="84.60", excerpt="1 USD = 84.60 INR", effective_date="2026-10-24")],
                    now=later(days=2))
    approve(store, POLICY, newer.proposal_id, "Reviewer B", later(days=2), note=NOTE, acknowledge_warnings=True)
    text = store.path.read_text(encoding="utf-8")
    assert text.count('"proposed_value":"84.60"') == 1
    store.path.write_text(text.replace('"proposed_value":"84.60"', '"proposed_value":"99.00"'), encoding="utf-8")
    return store


def test_fallback_note_on_entry_and_warning_to_caller(tmp_path):
    store = _two_approvals_latest_tampered(tmp_path)
    report = load_assumptions_report(store)
    fx = report.assumptions.fx_usd_inr
    assert fx.value == D("84.50")  # the earlier, valid approval
    assert FALLBACK in fx.evidence_note
    assert any(FALLBACK in w for w in report.warnings)
    assert any("evidence hash mismatch" in w and "ignored" in w for w in report.warnings)
    estimate = estimate_cost(golden_inputs(), report.assumptions)
    assert FALLBACK in next(e for e in estimate.assumptions if e.name == "fx_usd_inr").note


def test_fallback_warning_is_emitted_by_the_simple_loader(tmp_path):
    store = _two_approvals_latest_tampered(tmp_path)
    with pytest.warns(RateLoaderWarning) as caught:
        loaded = load_assumptions_with_store(store)
    messages = [str(w.message) for w in caught]
    assert any("using the approval from 2026-10-24" in m for m in messages)
    assert any("evidence hash mismatch" in m and "ignored" in m for m in messages)
    assert loaded.fx_usd_inr.value == D("84.50")


def test_no_fallback_note_when_nothing_was_ignored(tmp_path):
    store = make_store(tmp_path)
    propose_and_approve(store, POLICY, "fx_usd_inr", [statutory()])
    report = load_assumptions_report(store)
    assert "latest approval ignored" not in report.assumptions.fx_usd_inr.evidence_note
    assert report.warnings == []


def test_valid_approval_after_an_ignored_one_clears_the_fallback(tmp_path):
    store = _two_approvals_latest_tampered(tmp_path)
    third = propose(store, POLICY, "fx_usd_inr",
                    [statutory(value="84.70", excerpt="1 USD = 84.70 INR", effective_date="2026-10-24")],
                    now=later(days=3))
    approve(store, POLICY, third.proposal_id, "Reviewer C", later(days=3), note=NOTE, acknowledge_warnings=True)
    report = load_assumptions_report(store)
    assert report.assumptions.fx_usd_inr.value == D("84.70")
    assert "latest approval ignored" not in report.assumptions.fx_usd_inr.evidence_note
    assert not any("using the approval from" in w for w in report.warnings)


# ---- fixture data ------------------------------------------------------------------------------

def test_fixture_fetcher_marks_candidates_without_changing_the_originals():
    original = statutory()
    fetched = FixtureFetcher({"fx_usd_inr": [original]}).fetch("fx_usd_inr")
    assert fetched[0].is_fixture is True and original.is_fixture is False
    assert fetched[0].value == original.value


def test_is_fixture_must_be_a_bool():
    with pytest.raises(ValidationError):
        Candidate(**{**statutory().model_dump(), "is_fixture": "yes"})


def test_fixture_proposal_is_labelled_in_show(tmp_path):
    store = make_store(tmp_path)
    proposal = fixture_proposal(store)
    assert proposal.evidence_pack.fixture_data is True
    assert all(s.fixture for s in proposal.evidence_pack.sources)
    text = render_proposal(proposal, POLICY)
    assert text.splitlines()[0] == f"*** {FIXTURE_LABEL} ***"
    assert f"[{FIXTURE_LABEL}]" in text and "--allow-fixture" in text


def test_real_proposal_is_not_labelled(tmp_path):
    store = make_store(tmp_path)
    proposal = propose(store, POLICY, "fx_usd_inr", [statutory()])
    assert proposal.evidence_pack.fixture_data is False
    assert FIXTURE_LABEL not in render_proposal(proposal, POLICY)
    event = approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True)
    assert event.fixture_allowed is False


def test_approve_refuses_fixture_data_without_allow_fixture(tmp_path):
    store = make_store(tmp_path)
    proposal = fixture_proposal(store)
    with pytest.raises(ReviewError) as exc:
        approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True)
    assert exc.value.code == "fixture_data"
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.pending
    event = approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True,
                    allow_fixture=True)
    assert event.fixture_allowed is True
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.approved


def test_fixture_flag_is_covered_by_the_evidence_hash(tmp_path):
    store = make_store(tmp_path)
    proposal = fixture_proposal(store)
    text = store.path.read_text(encoding="utf-8")
    store.path.write_text(text.replace('"fixture_data":true', '"fixture_data":false'), encoding="utf-8")
    with pytest.raises(ReviewError) as exc:
        approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True)
    assert exc.value.code == "hash_mismatch"


def test_fixture_approval_is_marked_by_the_loader(tmp_path):
    store = make_store(tmp_path)
    proposal = fixture_proposal(store)
    approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True,
            allow_fixture=True)
    report = load_assumptions_report(store)
    assert FIXTURE_LABEL in report.assumptions.fx_usd_inr.evidence_note
    assert any("fixture data" in w for w in report.warnings)


def test_cli_requires_allow_fixture(tmp_path, capsys):
    store = make_store(tmp_path)
    real_now = datetime.now(timezone.utc)
    proposal = fixture_proposal(store, now=real_now, effective_date=(real_now.date() - timedelta(days=1)).isoformat())
    args = ["--store", str(store.path), "approve", proposal.proposal_id, "--by", "tester",
            "--acknowledge-warnings", "--note", NOTE]
    assert main(args) == 1
    assert "fixture_data" in capsys.readouterr().err
    assert main(["--store", str(store.path), "show", proposal.proposal_id]) == 0
    assert capsys.readouterr().out.splitlines()[0] == f"*** {FIXTURE_LABEL} ***"
    assert main(args + ["--allow-fixture"]) == 0
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.approved


def test_golden_case_unchanged(tmp_path):
    estimate = estimate_cost(golden_inputs(), load_cost_assumptions())
    assert (estimate.expected, estimate.per_unit_expected) == (D("154287.59"), D("1542.88"))


def test_new_strings_have_no_forbidden_words(tmp_path):
    store = _two_approvals_latest_tampered(tmp_path)
    texts = load_assumptions_report(store).warnings + [render_proposal(fixture_proposal(make_store(tmp_path, "f.jsonl")))]
    for text in texts:
        assert "fraud" not in text.lower() and "fake" not in text.lower()
