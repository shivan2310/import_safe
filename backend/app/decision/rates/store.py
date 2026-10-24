"""Append-only JSON-lines event store for rate proposals.

- One event per line. Earlier lines are never edited or deleted: an append copies the existing bytes unchanged,
  adds the new line, writes a temp file in the same folder and renames it over the original (atomic replace).
- A proposal's status is derived from its events (created -> pending; approved / rejected / superseded).
- A missing file is an empty store. A corrupt LAST line is skipped with a warning (reads keep working), but
  appending is refused until the file is repaired, so the bad line never ends up in the middle of the log.
- A corrupt EARLIER line, or events that contradict each other, raise StoreCorruptionError. Callers must not
  swallow it: review commands fail closed, and the investigation flow must catch it, fall back to the YAML
  placeholders and show a visible warning.
- Single writer only (MVP): there is no file locking.
"""
import os
from dataclasses import dataclass, field
from datetime import timezone
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import ValidationError

from app.decision.rates.models import (
    EVENT_ADAPTER,
    EvidenceKind,
    Proposal,
    ProposalApproved,
    ProposalCreated,
    ProposalRejected,
    ProposalStatus,
    ProposalSuperseded,
    RateKind,
    RateRecord,
    RejectionLogged,
    RejectionRecord,
    SourceRole,
    pack_hash,
)

DEFAULT_STORE_PATH = Path(__file__).resolve().parent / "data" / "rate_events.jsonl"
_TERMINAL = {
    "proposal_approved": ProposalStatus.approved,
    "proposal_rejected": ProposalStatus.rejected,
    "proposal_superseded": ProposalStatus.superseded,
}


class StoreCorruptionError(Exception):
    """The event log cannot be trusted (corrupt earlier line or contradictory events)."""


class StoreError(ValueError):
    """An append was refused (duplicate proposal, unknown proposal, proposal not pending)."""


@dataclass
class _State:
    raw: bytes = b""
    events: List = field(default_factory=list)
    last_line_corrupt: bool = False
    proposals: Dict[str, Proposal] = field(default_factory=dict)  # with derived status
    approvals: Dict[str, ProposalApproved] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)


def record_from(proposal: Proposal, approval: ProposalApproved) -> RateRecord:
    """The approved RateRecord for an approved proposal."""
    pack = proposal.evidence_pack
    common = dict(
        rate_key=proposal.rate_key, kind=proposal.kind, unit=pack.unit, effective_date=pack.effective_date,
        proposal_id=proposal.proposal_id, approved_by=approval.approver, approved_at=approval.approved_at,
        evidence_hash=approval.evidence_hash, fixture=pack.fixture_data,
    )
    if proposal.kind is RateKind.benchmark:
        stats = pack.benchmark
        return RateRecord(
            evidence_kind=EvidenceKind.benchmark, value=stats.median, range_low=stats.low, range_high=stats.high,
            source=f"market benchmark: {stats.sample_count} samples from {stats.domain_count} domains "
                   f"({', '.join(stats.domains)}); proposal {proposal.proposal_id}",
            sample_count=stats.sample_count, domain_count=stats.domain_count, **common,
        )
    primary = next(s for s in pack.sources if s.role is SourceRole.primary)
    return RateRecord(evidence_kind=EvidenceKind.official, value=pack.proposed_value, source=primary.url, **common)


class RateStore:
    def __init__(self, path: Union[str, Path, None] = None):
        self.path = Path(path) if path is not None else DEFAULT_STORE_PATH
        self.warnings: List[str] = []  # warnings from the most recent read

    # ---- reading -------------------------------------------------------------------------------

    def _read(self) -> _State:
        state = _State()
        if not self.path.exists():
            self.warnings = []
            return state
        state.raw = self.path.read_bytes()
        lines = state.raw.split(b"\n")
        numbered = [(i + 1, line) for i, line in enumerate(lines) if line.strip()]
        for position, (line_no, line) in enumerate(numbered):
            try:
                state.events.append(EVENT_ADAPTER.validate_json(line))
            except (ValidationError, ValueError) as exc:
                if position == len(numbered) - 1:
                    state.last_line_corrupt = True
                    state.warnings.append(
                        f"line {line_no}: corrupt last line skipped ({type(exc).__name__}); repair the file before "
                        "appending"
                    )
                else:
                    raise StoreCorruptionError(
                        f"{self.path}: line {line_no} is corrupt; the event log cannot be trusted"
                    ) from exc
        for event in state.events:
            self._apply(state, event)
        self.warnings = list(state.warnings)
        return state

    @staticmethod
    def _apply(state: _State, event) -> None:
        if isinstance(event, ProposalCreated):
            pid = event.proposal.proposal_id
            if pid in state.proposals:
                raise StoreCorruptionError(f"proposal {pid} is created twice in the event log")
            state.proposals[pid] = event.proposal
        elif isinstance(event, (ProposalApproved, ProposalRejected, ProposalSuperseded)):
            pid = event.proposal_id
            proposal = state.proposals.get(pid)
            if proposal is None:
                raise StoreCorruptionError(f"event {event.event_type} refers to unknown proposal {pid}")
            if proposal.status is not ProposalStatus.pending:
                raise StoreCorruptionError(f"event {event.event_type} for proposal {pid}, which is {proposal.status.value}")
            state.proposals[pid] = proposal.model_copy(update={"status": _TERMINAL[event.event_type]})
            if isinstance(event, ProposalApproved):
                state.approvals[pid] = event

    def proposals(self, status: Optional[ProposalStatus] = None) -> List[Proposal]:
        state = self._read()
        found = list(state.proposals.values())
        return [p for p in found if status is None or p.status is ProposalStatus(status)]

    def get_proposal(self, proposal_id: str) -> Optional[Proposal]:
        return self._read().proposals.get(proposal_id)

    def rejections(self, rate_key: Optional[str] = None) -> List[RejectionRecord]:
        state = self._read()
        return [e.rejection for e in state.events
                if isinstance(e, RejectionLogged) and (rate_key is None or e.rejection.rate_key == rate_key)]

    def history(self, rate_key: str) -> List:
        """Every event for rate_key, in log order."""
        state = self._read()
        keys = {pid: p.rate_key for pid, p in state.proposals.items()}
        out = []
        for e in state.events:
            if isinstance(e, ProposalCreated):
                key = e.proposal.rate_key
            elif isinstance(e, RejectionLogged):
                key = e.rejection.rate_key
            else:
                key = keys.get(e.proposal_id)
            if key == rate_key:
                out.append(e)
        return out

    def _approved(self, state: _State) -> Dict[str, RateRecord]:
        """Latest approved record per rate_key (log order). Approvals whose evidence hash does not match the
        stored pack are ignored with a warning; when that happens after a valid approval, the earlier approval
        is used and its record carries a fallback_note (also added to the warnings)."""
        records: Dict[str, RateRecord] = {}
        ignored_after: Dict[str, bool] = {}  # a newer approval than records[key] was ignored
        for e in state.events:
            if not isinstance(e, ProposalApproved):
                continue
            proposal = state.proposals[e.proposal_id]
            pack = proposal.evidence_pack
            if pack_hash(pack) != pack.content_hash or e.evidence_hash != pack.content_hash:
                state.warnings.append(
                    f"approval of {e.proposal_id} ({proposal.rate_key}) ignored: evidence hash mismatch"
                )
                ignored_after[proposal.rate_key] = True
                continue
            records[proposal.rate_key] = record_from(proposal, e)
            ignored_after[proposal.rate_key] = False
        for key, rec in list(records.items()):
            if ignored_after.get(key):
                used = rec.approved_at.astimezone(timezone.utc).date().isoformat()
                note = f"latest approval ignored (evidence hash mismatch); using the approval from {used}"
                records[key] = rec.model_copy(update={"fallback_note": note})
                state.warnings.append(f"{key}: {note}")
        self.warnings = list(state.warnings)
        return records

    def latest_approved(self, rate_key: str) -> Optional[RateRecord]:
        return self._approved(self._read()).get(rate_key)

    def approved_records(self) -> Dict[str, RateRecord]:
        return self._approved(self._read())

    # ---- writing -------------------------------------------------------------------------------

    def append_event(self, event) -> None:
        """Append one event atomically. Refuses events that would contradict the log."""
        state = self._read()
        if state.last_line_corrupt:
            raise StoreCorruptionError(f"{self.path}: the last line is corrupt; repair the file before appending")
        if isinstance(event, ProposalCreated):
            if event.proposal.proposal_id in state.proposals:
                raise StoreError(f"proposal {event.proposal.proposal_id} already exists")
        elif isinstance(event, (ProposalApproved, ProposalRejected, ProposalSuperseded)):
            proposal = state.proposals.get(event.proposal_id)
            if proposal is None:
                raise StoreError(f"unknown proposal {event.proposal_id}")
            if proposal.status is not ProposalStatus.pending:
                raise StoreError(f"proposal {event.proposal_id} is {proposal.status.value}, not pending")
        elif not isinstance(event, RejectionLogged):
            raise TypeError(f"not a store event: {type(event).__name__}")

        line = event.model_dump_json().encode("utf-8") + b"\n"
        separator = b"\n" if state.raw and not state.raw.endswith(b"\n") else b""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        try:
            with open(tmp, "wb") as fh:
                fh.write(state.raw + separator + line)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if tmp.exists():
                tmp.unlink()
