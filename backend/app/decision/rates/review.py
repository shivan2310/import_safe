"""Human review of rate proposals: decision functions plus a small CLI. Approval is CLI only (no HTTP endpoint).

The MVP has NO AUTHENTICATION: the name given with --by is self-reported and stored as given.

Usage (run from backend/):
    python -m app.decision.rates.review list [--status pending]
    python -m app.decision.rates.review show <proposal_id>
    python -m app.decision.rates.review approve <proposal_id> --by NAME [--note TEXT] [--acknowledge-warnings]
        [--allow-fixture]   (required for proposals built from fixture data)
    python -m app.decision.rates.review reject <proposal_id> --by NAME --reason TEXT
Options before the command: --store PATH (event log), --policy PATH (rate policy).

The review functions take `now` as an argument and never read the clock; only main() does.
A proposal with warnings needs --acknowledge-warnings and a non-empty --note. Proposals that are not pending,
are older than proposal_expiry_days, or whose evidence pack no longer matches its hash cannot be approved.
"""
import argparse
import sys
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence

from app.decision.rates.checks import fmt, fmt_pct
from app.decision.rates.models import (
    Proposal,
    ProposalApproved,
    ProposalRejected,
    ProposalStatus,
    RateKind,
    pack_hash,
)
from app.decision.rates.policy import Policy, load_policy
from app.decision.rates.store import RateStore, StoreCorruptionError, StoreError

AUTH_NOTE = "Approver names are self-reported; the MVP has no authentication."
FIXTURE_LABEL = "FIXTURE DATA, NOT REAL EVIDENCE"
_TIER_NAMES = {1: "official", 2: "secondary", 3: "other"}


class ReviewError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def clean(text: Optional[str]) -> str:
    """Untrusted text made safe to print on one line: control and format characters become '?', and line breaks
    and tabs become spaces so page text cannot imitate this tool's own output lines."""
    if text is None:
        return ""
    out = []
    for ch in text:
        if ch in "\n\r\t":
            out.append(" ")
        elif unicodedata.category(ch).startswith("C"):
            out.append("?")
        else:
            out.append(ch)
    return "".join(out)


def _require_aware(now: datetime) -> None:
    if not isinstance(now, datetime) or now.utcoffset() is None:
        raise ValueError("now must be a timezone-aware datetime")


def _expires_at(proposal: Proposal, policy: Policy) -> Optional[datetime]:
    rp = policy.rates.get(proposal.rate_key)
    return None if rp is None else proposal.created_at + timedelta(days=rp.proposal_expiry_days)


def check_approval(
    proposal: Proposal, policy: Policy, approver: str, now: datetime,
    note: Optional[str] = None, acknowledge_warnings: bool = False, allow_fixture: bool = False,
) -> str:
    """Raise ReviewError if the proposal cannot be approved; return the cleaned approver name. Pure."""
    _require_aware(now)
    name = (approver or "").strip()
    if not name:
        raise ReviewError("approver_required", "An approver name is required (--by NAME).")
    if proposal.status is not ProposalStatus.pending:
        raise ReviewError("not_pending", f"Proposal {proposal.proposal_id} is {proposal.status.value}; "
                                         "only pending proposals can be approved.")
    expires = _expires_at(proposal, policy)
    if expires is None:
        raise ReviewError("no_policy", f"No policy entry for {proposal.rate_key}; it cannot be approved.")
    if now > expires:
        raise ReviewError("expired", f"Proposal {proposal.proposal_id} expired at {expires.isoformat()}; "
                                     "run a new refresh instead.")
    pack = proposal.evidence_pack
    if pack_hash(pack) != pack.content_hash:
        raise ReviewError("hash_mismatch", "The evidence pack no longer matches its recorded hash; it changed after "
                                           "it was created. Not approved.")
    if pack.fixture_data and not allow_fixture:
        raise ReviewError("fixture_data", f"{FIXTURE_LABEL}: this proposal was built from fixture data; approving it "
                                          "needs an explicit --allow-fixture.")
    if pack.warnings:
        if not acknowledge_warnings:
            raise ReviewError("warnings_not_acknowledged",
                              f"This proposal has {len(pack.warnings)} warning(s); approving it needs "
                              "--acknowledge-warnings and a --note.")
        if not (note or "").strip():
            raise ReviewError("note_required", "Acknowledging warnings requires a non-empty --note.")
    return name


def approve(
    store: RateStore, policy: Policy, proposal_id: str, approver: str, now: datetime,
    note: Optional[str] = None, acknowledge_warnings: bool = False, allow_fixture: bool = False,
) -> ProposalApproved:
    """Append a ProposalApproved event after every check passes. Earlier lines are never edited."""
    if not (approver or "").strip():
        raise ReviewError("approver_required", "An approver name is required (--by NAME).")
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise ReviewError("not_found", f"No proposal {proposal_id}.")
    name = check_approval(proposal, policy, approver, now, note, acknowledge_warnings, allow_fixture)
    pack = proposal.evidence_pack
    event = ProposalApproved(
        proposal_id=proposal_id, approver=name, approved_at=now, note=(note or "").strip() or None,
        acknowledged_warnings=list(pack.warnings) if acknowledge_warnings else [], evidence_hash=pack.content_hash,
        fixture_allowed=pack.fixture_data,
    )
    try:
        store.append_event(event)
    except StoreError as exc:
        raise ReviewError("refused_by_store", str(exc)) from exc
    return event


def reject(store: RateStore, proposal_id: str, reviewer: str, reason: str, now: datetime) -> ProposalRejected:
    """Append a ProposalRejected event with the reviewer's reason."""
    _require_aware(now)
    name = (reviewer or "").strip()
    if not name:
        raise ReviewError("reviewer_required", "A reviewer name is required (--by NAME).")
    text = (reason or "").strip()
    if not text:
        raise ReviewError("reason_required", "A rejection needs a non-empty --reason.")
    proposal = store.get_proposal(proposal_id)
    if proposal is None:
        raise ReviewError("not_found", f"No proposal {proposal_id}.")
    if proposal.status is not ProposalStatus.pending:
        raise ReviewError("not_pending", f"Proposal {proposal_id} is {proposal.status.value}; "
                                         "only pending proposals can be rejected.")
    event = ProposalRejected(proposal_id=proposal_id, reviewer=name, rejected_at=now, reason=text)
    try:
        store.append_event(event)
    except StoreError as exc:
        raise ReviewError("refused_by_store", str(exc)) from exc
    return event


# ---- plain-language rendering ------------------------------------------------------------------

def render_list(proposals: Sequence[Proposal]) -> str:
    if not proposals:
        return "No proposals."
    lines = []
    for p in sorted(proposals, key=lambda p: (p.created_at, p.proposal_id)):
        pack = p.evidence_pack
        lines.append(
            f"{p.proposal_id}  {p.rate_key}  {p.kind.value}  {p.status.value}  "
            f"{fmt(pack.proposed_value)} {pack.unit}  created {p.created_at.isoformat()}  "
            f"warnings: {len(pack.warnings)}"
        )
    return "\n".join(lines)


def _pct(value) -> str:
    return "unbounded" if value is None else f"{fmt_pct(value)}%"


def render_proposal(proposal: Proposal, policy: Optional[Policy] = None) -> str:
    """Full evidence pack in plain language. Page text is cleaned before display."""
    pack = proposal.evidence_pack
    out: List[str] = []
    if pack.fixture_data:
        out.append(f"*** {FIXTURE_LABEL} ***")
    out.append(f"Proposal {proposal.proposal_id}: {proposal.rate_key} ({proposal.kind.value}), "
               f"status {proposal.status.value}")
    out.append(f"Created: {proposal.created_at.isoformat()}")
    if policy is not None:
        expires = _expires_at(proposal, policy)
        if expires is not None:
            out.append(f"Can be approved until: {expires.isoformat()}")
    if pack.benchmark is not None:
        b = pack.benchmark
        out.append(f"Proposed benchmark: low {fmt(b.low)}, median {fmt(b.median)}, high {fmt(b.high)} {pack.unit}")
        out.append(f"Market benchmark, not an official figure: {b.sample_count} samples from {b.domain_count} "
                   f"domains ({', '.join(clean(d) for d in b.domains)})")
        if b.outlier_domains:
            out.append(f"Outlier domains removed: {', '.join(clean(d) for d in b.outlier_domains)}")
    else:
        out.append(f"Proposed value: {fmt(pack.proposed_value)} {pack.unit}")
    out.append(f"Effective date: {pack.effective_date or 'not given'}")
    if pack.reconfirmation:
        out.append("Reconfirmation: same value as the approved record, newer effective date.")
    if pack.current_value is not None:
        out.append(f"Current approved value: {fmt(pack.current_value)} (effective {pack.current_effective_date}, "
                   f"proposal {pack.current_proposal_id}); change {fmt(pack.change_abs)} ({_pct(pack.change_pct)})")
    else:
        out.append("Current approved value: none (first approval).")
        if pack.placeholder_value is not None:
            out.append(f"Information only: YAML placeholder {fmt(pack.placeholder_value)} "
                       f"({clean(pack.placeholder_detail)}); change {_pct(pack.placeholder_change_pct)}")
    out.append("Sources:")
    for i, s in enumerate(pack.sources, start=1):
        out.append(f"  [{i}] {s.role.value}: tier {s.tier} ({_TIER_NAMES.get(s.tier, '?')}), {clean(s.domain)}"
                   f"{'' if s.claimed_tier == s.tier else f' (fetcher claimed tier {s.claimed_tier})'}"
                   f"{' [' + FIXTURE_LABEL + ']' if s.fixture else ''}")
        out.append(f"      URL: {clean(s.url)}")
        out.append(f"      Retrieved: {s.retrieved_at.isoformat()}; value {fmt(s.value)} {clean(s.unit)}; "
                   f"effective {clean(s.effective_date) or 'not given'}")
        if s.snapshot_ref:
            out.append(f"      Snapshot: {clean(s.snapshot_ref)}")
        out.append(f"      Excerpt{' (truncated)' if s.excerpt_truncated else ''}: \"{clean(s.excerpt)}\"")
    if proposal.kind is RateKind.statutory:
        out.append(f"Agreement: {pack.agreeing_domains} independent tier-2/3 domain(s) agree ({pack.corroboration}).")
    if pack.disagreements:
        out.append("Disagreements (recorded, never averaged):")
        for d in pack.disagreements:
            out.append(f"  - {clean(d.detail)}")
    else:
        out.append("Disagreements: none.")
    out.append("Checks:")
    for c in pack.check_results:
        status = "PASS" if c.passed else f"FAIL ({c.severity.value})"
        subject = f" [{clean(c.subject)}]" if c.subject else ""
        out.append(f"  {status} {c.name}{subject}: {clean(c.detail)}")
    if pack.warnings:
        out.append("Warnings (approval needs --acknowledge-warnings and a --note):")
        for w in pack.warnings:
            out.append(f"  - {clean(w)}")
    else:
        out.append("Warnings: none.")
    if pack.fixture_data:
        out.append(f"{FIXTURE_LABEL}: approval needs an explicit --allow-fixture.")
    out.append(f"Evidence hash: {pack.content_hash}")
    out.append("Read the official excerpt yourself: agreement between websites is not proof of correctness.")
    out.append(AUTH_NOTE)
    return "\n".join(out)


# ---- CLI ---------------------------------------------------------------------------------------

def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.decision.rates.review",
                                     description="Review rate proposals. " + AUTH_NOTE)
    parser.add_argument("--store", help="path to the event log (default: app/decision/rates/data/rate_events.jsonl)")
    parser.add_argument("--policy", help="path to the rate policy (default: app/decision/rates/policy.yaml)")
    sub = parser.add_subparsers(dest="command", required=True)
    listing = sub.add_parser("list", help="list proposals")
    listing.add_argument("--status", choices=[s.value for s in ProposalStatus])
    show = sub.add_parser("show", help="show one proposal's evidence pack")
    show.add_argument("proposal_id")
    approve_cmd = sub.add_parser("approve", help="approve a pending proposal")
    approve_cmd.add_argument("proposal_id")
    approve_cmd.add_argument("--by", required=True, help="approver name (self-reported)")
    approve_cmd.add_argument("--note")
    approve_cmd.add_argument("--acknowledge-warnings", action="store_true")
    approve_cmd.add_argument("--allow-fixture", action="store_true",
                             help="required to approve a proposal built from fixture (test) data")
    reject_cmd = sub.add_parser("reject", help="reject a pending proposal")
    reject_cmd.add_argument("proposal_id")
    reject_cmd.add_argument("--by", required=True, help="reviewer name (self-reported)")
    reject_cmd.add_argument("--reason", required=True)
    return parser


def _safe_stdout() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    _safe_stdout()
    store = RateStore(args.store) if args.store else RateStore()
    try:
        if args.command == "list":
            print(render_list(store.proposals(ProposalStatus(args.status) if args.status else None)))
        elif args.command == "show":
            proposal = store.get_proposal(args.proposal_id)
            if proposal is None:
                raise ReviewError("not_found", f"No proposal {args.proposal_id}.")
            print(render_proposal(proposal, load_policy(args.policy)))
        elif args.command == "approve":
            now = datetime.now(timezone.utc)
            event = approve(store, load_policy(args.policy), args.proposal_id, args.by, now,
                            note=args.note, acknowledge_warnings=args.acknowledge_warnings,
                            allow_fixture=args.allow_fixture)
            print(f"Approved {event.proposal_id} by {clean(event.approver)} at {event.approved_at.isoformat()}.")
            print(AUTH_NOTE)
        elif args.command == "reject":
            now = datetime.now(timezone.utc)
            event = reject(store, args.proposal_id, args.by, args.reason, now)
            print(f"Rejected {event.proposal_id} by {clean(event.reviewer)}: {clean(event.reason)}")
            print(AUTH_NOTE)
    except ReviewError as exc:
        print(f"Refused ({exc.code}): {exc.message}", file=sys.stderr)
        return 1
    except StoreCorruptionError as exc:
        print(f"Store error, no action taken: {exc}", file=sys.stderr)
        return 3
    for warning in store.warnings:
        print(f"Store warning: {warning}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
