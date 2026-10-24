from decimal import Decimal as D

import pytest

from app.decision.rates.builder import build_proposal
from app.decision.rates.models import (
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalStatus,
    ProposalSuperseded,
    RejectionLogged,
)
from app.decision.rates.store import DEFAULT_STORE_PATH, RateStore, StoreCorruptionError, StoreError
from tests.rate_helpers import NOW, POLICY, approve, later, make_store, propose, statutory


def _proposal(value="84.50", now=NOW):
    return build_proposal("fx_usd_inr", [statutory(value=value, excerpt=f"1 USD = {value} INR")], None, POLICY, now)


def test_missing_file_is_an_empty_store(tmp_path):
    store = make_store(tmp_path)
    assert store.proposals() == []
    assert store.latest_approved("fx_usd_inr") is None
    assert store.history("fx_usd_inr") == []
    assert store.warnings == []
    assert not store.path.exists()


def test_store_is_append_only_and_earlier_lines_stay_byte_identical(tmp_path):
    store = make_store(tmp_path)
    proposal = propose(store, POLICY, "fx_usd_inr", [statutory()])
    first = store.path.read_bytes()
    rejection = build_proposal("fx_usd_inr", [statutory(url="https://news.example/fx")], None, POLICY, NOW)
    store.append_event(RejectionLogged(rejection=rejection))
    second = store.path.read_bytes()
    assert second.startswith(first) and len(second) > len(first)
    approve(store, POLICY, proposal)
    third = store.path.read_bytes()
    assert third.startswith(second)
    assert third.count(b"\n") == 3
    assert sorted(p.name for p in tmp_path.iterdir()) == ["events.jsonl"]  # no temp files left behind


def test_status_is_derived_from_events(tmp_path):
    store = make_store(tmp_path)
    a = propose(store, POLICY, "fx_usd_inr", [statutory()])
    assert store.get_proposal(a.proposal_id).status is ProposalStatus.pending
    b = _proposal("84.60", later(hours=1))
    store.append_event(ProposalCreated(proposal=b))
    store.append_event(ProposalSuperseded(proposal_id=a.proposal_id, superseded_by=b.proposal_id,
                                          superseded_at=later(hours=1)))
    assert store.get_proposal(a.proposal_id).status is ProposalStatus.superseded
    store.append_event(ProposalRejected(proposal_id=b.proposal_id, reviewer="Reviewer B", rejected_at=later(hours=2),
                                        reason="Excerpt is from a draft notification."))
    assert store.get_proposal(b.proposal_id).status is ProposalStatus.rejected
    assert [p.proposal_id for p in store.proposals(ProposalStatus.pending)] == []
    assert len(store.proposals()) == 2
    assert [type(e).__name__ for e in store.history("fx_usd_inr")] == [
        "ProposalCreated", "ProposalCreated", "ProposalSuperseded", "ProposalRejected"]
    assert store.history("bcd_pct") == []


def test_duplicate_proposal_created_is_refused(tmp_path):
    store = make_store(tmp_path)
    proposal = propose(store, POLICY, "fx_usd_inr", [statutory()])
    before = store.path.read_bytes()
    with pytest.raises(StoreError):
        store.append_event(ProposalCreated(proposal=proposal))
    assert store.path.read_bytes() == before


def test_events_for_unknown_or_finished_proposals_are_refused(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(StoreError):
        store.append_event(ProposalRejected(proposal_id="prop_missing", reviewer="R", rejected_at=NOW, reason="x"))
    proposal = propose(store, POLICY, "fx_usd_inr", [statutory()])
    approve(store, POLICY, proposal)
    with pytest.raises(StoreError):
        store.append_event(ProposalRejected(proposal_id=proposal.proposal_id, reviewer="R", rejected_at=NOW, reason="x"))
    with pytest.raises(TypeError):
        store.append_event(proposal)  # a Proposal is not an event


def test_corrupt_last_line_is_skipped_with_warning_and_blocks_appends(tmp_path):
    store = make_store(tmp_path)
    proposal = propose(store, POLICY, "fx_usd_inr", [statutory()])
    with open(store.path, "ab") as fh:
        fh.write(b'{"event_type": "proposal_approved", "proposal_id": ')  # truncated write
    assert [p.proposal_id for p in store.proposals()] == [proposal.proposal_id]
    assert len(store.warnings) == 1 and "corrupt last line" in store.warnings[0]
    damaged = store.path.read_bytes()
    with pytest.raises(StoreCorruptionError):
        store.append_event(RejectionLogged(rejection=build_proposal(
            "fx_usd_inr", [statutory(url="https://news.example/fx")], None, POLICY, NOW)))
    assert store.path.read_bytes() == damaged


def test_corrupt_earlier_line_raises(tmp_path):
    store = make_store(tmp_path)
    propose(store, POLICY, "fx_usd_inr", [statutory()])
    good = store.path.read_bytes()
    store.path.write_bytes(b"not json at all\n" + good)
    with pytest.raises(StoreCorruptionError):
        store.proposals()
    with pytest.raises(StoreCorruptionError):
        store.latest_approved("fx_usd_inr")


def test_contradictory_events_raise(tmp_path):
    store = make_store(tmp_path)
    proposal = propose(store, POLICY, "fx_usd_inr", [statutory()])
    line = ProposalApproved(proposal_id="prop_unknown", approver="R", approved_at=NOW,
                            evidence_hash="sha256:x").model_dump_json().encode() + b"\n"
    created_twice = ProposalCreated(proposal=proposal).model_dump_json().encode() + b"\n"
    store.path.write_bytes(store.path.read_bytes() + line + created_twice)
    with pytest.raises(StoreCorruptionError):
        store.proposals()


def test_latest_approved_follows_log_order(tmp_path):
    store = make_store(tmp_path)
    first = propose(store, POLICY, "fx_usd_inr", [statutory()])
    approve(store, POLICY, first)
    second = propose(store, POLICY, "fx_usd_inr",
                     [statutory(value="84.60", excerpt="1 USD = 84.60 INR", effective_date="2026-10-24")],
                     now=later(hours=1))
    assert store.latest_approved("fx_usd_inr").value == D("84.50")  # second is still pending
    approve(store, POLICY, second, now=later(hours=2))
    record = store.latest_approved("fx_usd_inr")
    assert record.value == D("84.60") and record.proposal_id == second.proposal_id
    assert record.approved_by == "Reviewer A" and record.evidence_hash == second.evidence_pack.content_hash
    assert record.source == statutory().source_url


def test_approval_with_changed_pack_is_ignored_with_warning(tmp_path):
    store = make_store(tmp_path)
    proposal = propose(store, POLICY, "fx_usd_inr", [statutory()])
    approve(store, POLICY, proposal)
    text = store.path.read_text(encoding="utf-8")
    assert text.count('"proposed_value":"84.50"') == 1
    store.path.write_text(text.replace('"proposed_value":"84.50"', '"proposed_value":"80.00"'), encoding="utf-8")
    assert store.latest_approved("fx_usd_inr") is None
    assert any("evidence hash mismatch" in w for w in store.warnings)


def test_default_store_path_is_under_rates_data_with_its_own_gitignore():
    assert DEFAULT_STORE_PATH.parent.name == "data"
    assert DEFAULT_STORE_PATH.parent.parent.name == "rates"
    gitignore = (DEFAULT_STORE_PATH.parent / ".gitignore").read_text(encoding="utf-8")
    assert "*" in gitignore.split() and "!.gitignore" in gitignore.split()


def test_store_reads_events_written_by_another_instance(tmp_path):
    writer = make_store(tmp_path)
    proposal = propose(writer, POLICY, "fx_usd_inr", [statutory()])
    reader = RateStore(writer.path)
    assert reader.get_proposal(proposal.proposal_id) == proposal
