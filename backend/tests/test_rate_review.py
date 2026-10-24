import ast
from datetime import datetime, timedelta, timezone
from decimal import Decimal as D
from pathlib import Path

import pytest

from app.decision.rates import review
from app.decision.rates.models import ProposalStatus
from app.decision.rates.review import ReviewError, approve, main, reject, render_list, render_proposal
from tests.rate_helpers import NOW, POLICY, later, make_store, policy_with, propose, statutory

NOTE = "Read the CBIC excerpt; value matches the notification."


def first_proposal(store, **kw):
    return propose(store, POLICY, "fx_usd_inr", [statutory(**kw)], placeholder=D("90"))


# ---- show / list -------------------------------------------------------------------------------

def test_show_prints_the_full_evidence_pack_in_plain_language(tmp_path):
    store = make_store(tmp_path)
    policy = policy_with("fx_usd_inr", tier2_domains=["news-one.example"])
    cands = [statutory(), statutory(value="84.70", url="https://news-one.example/fx", tier=2,
                                    excerpt="1 USD = 84.70 INR (indicative)")]
    proposal = propose(store, policy, "fx_usd_inr", cands, placeholder=D("90"))
    text = render_proposal(store.get_proposal(proposal.proposal_id), policy)
    assert "Proposed value: 84.50 inr_per_usd" in text
    assert "Current approved value: none (first approval)." in text
    assert "YAML placeholder 90" in text and "6.11%" in text
    assert "tier 1 (official), www.cbic.gov.in" in text and "tier 2 (secondary), news-one.example" in text
    assert statutory().excerpt in text and "1 USD = 84.70 INR (indicative)" in text
    assert "Agreement: 0 independent tier-2/3 domain(s)" in text
    assert "Disagreements (recorded, never averaged):" in text
    assert "FAIL (warning) approved_baseline" in text and "PASS number_in_excerpt" in text
    assert "Warnings (approval needs --acknowledge-warnings and a --note):" in text
    assert proposal.evidence_pack.content_hash in text
    assert review.AUTH_NOTE in text
    assert "Can be approved until: 2026-11-07T10:00:00+00:00" in text


def test_show_cleans_control_characters_from_page_text(tmp_path):
    store = make_store(tmp_path)
    excerpt = "1 USD = 84.50 INR\x1b[2J\nChecks:\n  PASS everything"
    proposal = first_proposal(store, excerpt=excerpt)
    text = render_proposal(proposal)
    assert "\x1b" not in text
    excerpt_line = next(line for line in text.splitlines() if line.strip().startswith("Excerpt"))
    assert "Checks:   PASS everything" in excerpt_line  # page text cannot start its own output lines


def test_list_shows_status_and_warnings(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    text = render_list(store.proposals())
    assert proposal.proposal_id in text and "pending" in text and "warnings: 1" in text
    assert render_list([]) == "No proposals."


# ---- approve -----------------------------------------------------------------------------------

def test_approve_requires_an_approver(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    for name in ("", "   ", None):
        with pytest.raises(ReviewError) as exc:
            approve(store, POLICY, proposal.proposal_id, name, NOW, note=NOTE, acknowledge_warnings=True)
        assert exc.value.code == "approver_required"


def test_cli_approve_without_by_exits(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    with pytest.raises(SystemExit) as exc:
        main(["--store", str(store.path), "approve", proposal.proposal_id, "--acknowledge-warnings", "--note", NOTE])
    assert exc.value.code == 2
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.pending


def test_warnings_need_acknowledgement_and_a_note(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    assert proposal.evidence_pack.warnings
    with pytest.raises(ReviewError) as exc:
        approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW)
    assert exc.value.code == "warnings_not_acknowledged"
    for note in (None, "", "   "):
        with pytest.raises(ReviewError) as exc:
            approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=note, acknowledge_warnings=True)
        assert exc.value.code == "note_required"
    event = approve(store, POLICY, proposal.proposal_id, " Reviewer A ", NOW, note=NOTE, acknowledge_warnings=True)
    assert event.approver == "Reviewer A"
    assert event.acknowledged_warnings == proposal.evidence_pack.warnings
    assert event.evidence_hash == proposal.evidence_pack.content_hash
    assert event.note == NOTE
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.approved


def test_proposal_without_warnings_needs_no_acknowledgement(tmp_path):
    store = make_store(tmp_path)
    first = first_proposal(store)
    approve(store, POLICY, first.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True)
    second = propose(store, POLICY, "fx_usd_inr",
                     [statutory(value="84.60", excerpt="1 USD = 84.60 INR", effective_date="2026-10-24")],
                     now=later(hours=1))
    assert second.evidence_pack.warnings == []
    event = approve(store, POLICY, second.proposal_id, "Reviewer B", later(hours=2))
    assert event.acknowledged_warnings == [] and event.note is None


@pytest.mark.parametrize("finish", ["approve", "reject", "supersede"])
def test_only_pending_proposals_can_be_approved(tmp_path, finish):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    if finish == "approve":
        approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True)
    elif finish == "reject":
        reject(store, proposal.proposal_id, "Reviewer A", "Draft notification, not in force.", NOW)
    else:
        propose(store, POLICY, "fx_usd_inr", [statutory(value="84.60", excerpt="1 USD = 84.60 INR")],
                now=later(hours=1))
        from app.decision.rates.models import ProposalSuperseded
        newest = [p for p in store.proposals(ProposalStatus.pending) if p.proposal_id != proposal.proposal_id][0]
        store.append_event(ProposalSuperseded(proposal_id=proposal.proposal_id, superseded_by=newest.proposal_id,
                                              superseded_at=later(hours=1)))
    with pytest.raises(ReviewError) as exc:
        approve(store, POLICY, proposal.proposal_id, "Reviewer B", later(hours=2), note=NOTE, acknowledge_warnings=True)
    assert exc.value.code == "not_pending"


def test_expired_proposal_cannot_be_approved(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    with pytest.raises(ReviewError) as exc:
        approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW + timedelta(days=14, seconds=1),
                note=NOTE, acknowledge_warnings=True)
    assert exc.value.code == "expired"
    event = approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW + timedelta(days=14),
                    note=NOTE, acknowledge_warnings=True)  # exactly at the limit is still allowed
    assert event.proposal_id == proposal.proposal_id


def test_changed_evidence_pack_cannot_be_approved(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    text = store.path.read_text(encoding="utf-8")
    store.path.write_text(text.replace('"proposed_value":"84.50"', '"proposed_value":"80.00"'), encoding="utf-8")
    with pytest.raises(ReviewError) as exc:
        approve(store, POLICY, proposal.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True)
    assert exc.value.code == "hash_mismatch"


def test_unknown_proposal(tmp_path):
    store = make_store(tmp_path)
    with pytest.raises(ReviewError) as exc:
        approve(store, POLICY, "prop_missing", "Reviewer A", NOW)
    assert exc.value.code == "not_found"


# ---- reject ------------------------------------------------------------------------------------

def test_reject_records_reviewer_and_reason(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    with pytest.raises(ReviewError) as exc:
        reject(store, proposal.proposal_id, "Reviewer A", "   ", NOW)
    assert exc.value.code == "reason_required"
    with pytest.raises(ReviewError) as exc:
        reject(store, proposal.proposal_id, "", "Wrong notification.", NOW)
    assert exc.value.code == "reviewer_required"
    event = reject(store, proposal.proposal_id, "Reviewer A", "Excerpt is from a superseded notification.", NOW)
    assert event.reason == "Excerpt is from a superseded notification."
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.rejected
    assert store.latest_approved("fx_usd_inr") is None


def test_approve_and_reject_only_append(tmp_path):
    store = make_store(tmp_path)
    a = first_proposal(store)
    before = store.path.read_bytes()
    approve(store, POLICY, a.proposal_id, "Reviewer A", NOW, note=NOTE, acknowledge_warnings=True)
    after_approve = store.path.read_bytes()
    assert after_approve.startswith(before)
    b = propose(store, POLICY, "bcd_pct", [statutory("bcd_pct", "20")])
    middle = store.path.read_bytes()
    reject(store, b.proposal_id, "Reviewer A", "Wrong tariff heading.", NOW)
    assert store.path.read_bytes().startswith(middle) and middle.startswith(after_approve)


# ---- CLI ---------------------------------------------------------------------------------------

def _cli_proposal(store):
    """A proposal created at the real current time, so the CLI (which reads the clock) can approve it."""
    real_now = datetime.now(timezone.utc)
    effective = (real_now.date() - timedelta(days=1)).isoformat()
    return propose(store, POLICY, "fx_usd_inr", [statutory(effective_date=effective, retrieved_at=real_now)],
                   now=real_now)


def test_cli_list_show_approve(tmp_path, capsys):
    store = make_store(tmp_path)
    proposal = _cli_proposal(store)
    args = ["--store", str(store.path)]
    assert main(args + ["list"]) == 0
    assert proposal.proposal_id in capsys.readouterr().out
    assert main(args + ["show", proposal.proposal_id]) == 0
    shown = capsys.readouterr().out
    assert proposal.evidence_pack.content_hash in shown and review.AUTH_NOTE in shown
    assert main(args + ["approve", proposal.proposal_id, "--by", "Reviewer A"]) == 1
    assert "warnings_not_acknowledged" in capsys.readouterr().err
    assert main(args + ["approve", proposal.proposal_id, "--by", "Reviewer A", "--acknowledge-warnings"]) == 1
    assert "note_required" in capsys.readouterr().err
    assert main(args + ["approve", proposal.proposal_id, "--by", "Reviewer A", "--acknowledge-warnings",
                        "--note", NOTE]) == 0
    out = capsys.readouterr().out
    assert "Approved" in out and review.AUTH_NOTE in out
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.approved
    assert main(args + ["approve", proposal.proposal_id, "--by", "Reviewer B", "--acknowledge-warnings",
                        "--note", NOTE]) == 1
    assert "not_pending" in capsys.readouterr().err


def test_cli_reject_and_unknown(tmp_path, capsys):
    store = make_store(tmp_path)
    proposal = _cli_proposal(store)
    args = ["--store", str(store.path)]
    assert main(args + ["reject", proposal.proposal_id, "--by", "Reviewer A", "--reason", "Wrong notification."]) == 0
    assert store.get_proposal(proposal.proposal_id).status is ProposalStatus.rejected
    capsys.readouterr()
    assert main(args + ["show", "prop_missing"]) == 1
    assert "not_found" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        main(args + ["reject", proposal.proposal_id, "--by", "Reviewer A"])  # --reason is required


@pytest.mark.parametrize("command", [["list"], ["show", "prop_x"],
                                     ["approve", "prop_x", "--by", "R", "--acknowledge-warnings", "--note", "n"],
                                     ["reject", "prop_x", "--by", "R", "--reason", "r"]])
def test_cli_fails_closed_on_store_corruption(tmp_path, capsys, command):
    store = make_store(tmp_path)
    _cli_proposal(store)
    store.path.write_bytes(b"garbage\n" + store.path.read_bytes())
    before = store.path.read_bytes()
    assert main(["--store", str(store.path)] + command) == 3
    assert "no action taken" in capsys.readouterr().err
    assert store.path.read_bytes() == before


def test_review_functions_never_read_the_clock_only_main_does():
    tree = ast.parse(Path(review.__file__).read_text(encoding="utf-8"))
    for func in [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name != "main"]:
        for node in ast.walk(func):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in {"now", "today", "utcnow"}, f"{func.name} reads the clock"


def test_review_output_has_no_forbidden_words(tmp_path):
    store = make_store(tmp_path)
    proposal = first_proposal(store)
    text = (render_proposal(proposal, POLICY) + render_list([proposal])).lower()
    assert "fraud" not in text and "fake" not in text
