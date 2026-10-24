"""Storage the coordinator needs, as a Protocol, plus an in-memory implementation.

The coordinator depends only on ``InvestigationStore``. ``InMemoryStore`` is used by the tests and by local runs
without a database. A Postgres implementation over ``app.db.repositories`` is wired in Step 9; it needs a
progress-events table, which the Step 6 schema does not have yet.
"""
import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, List, Optional, Protocol, Sequence, Tuple

from app.coordinator.states import InvestigationState, TERMINAL
from app.db.repositories import (
    QUESTION_ANSWERED, QUESTION_OPEN, QUESTION_SKIPPED, EvidenceIn, EvidenceRow, FactIn, FactRow, QuestionIn,
    QuestionRow,
)
from app.decision.cost_engine import CostEstimate, CostOverrides
from app.decision.enums import StageState
from app.decision.report_schema import FullReport


@dataclass(frozen=True)
class OrderInput:
    """What the buyer typed in (docs/prd-backend.md B3). Money is Decimal in INR."""

    url: str
    quantity: int
    purpose: Optional[str] = None
    destination_state: Optional[str] = None
    destination_city: Optional[str] = None
    variant: Optional[str] = None
    freight_inr: Optional[Decimal] = None
    insurance_inr: Optional[Decimal] = None
    seller_certificates: Tuple[str, ...] = ()
    overrides: Optional[CostOverrides] = None


@dataclass(frozen=True)
class ProgressEvent:
    stage: str
    state: StageState
    message: str
    at: datetime


class InvestigationStore(Protocol):
    async def get_state(self, investigation_id: str) -> Optional[InvestigationState]: ...

    async def transition(self, investigation_id: str, from_state: InvestigationState,
                         to_state: InvestigationState) -> bool:
        """Atomic compare-and-set. False when the stored state is not ``from_state``."""
        ...

    async def force_state(self, investigation_id: str, to_state: InvestigationState) -> Optional[InvestigationState]:
        """Move to ``to_state`` unless already terminal. Returns the previous state, or None if unchanged."""
        ...

    async def get_order(self, investigation_id: str) -> Optional[OrderInput]: ...
    async def add_event(self, investigation_id: str, event: ProgressEvent) -> None: ...
    async def list_events(self, investigation_id: str) -> List[ProgressEvent]: ...
    async def save_facts(self, investigation_id: str, facts: Sequence[FactIn]) -> None: ...
    async def list_facts(self, investigation_id: str) -> List[FactRow]: ...
    async def save_evidence(self, investigation_id: str, items: Sequence[EvidenceIn]) -> None: ...
    async def list_evidence(self, investigation_id: str) -> List[EvidenceRow]: ...
    async def save_question(self, investigation_id: str, question: QuestionIn) -> None: ...
    async def list_questions(self, investigation_id: str) -> List[QuestionRow]: ...

    async def resolve_question(self, investigation_id: str, question_id: str, answer: Optional[str],
                               skipped: bool) -> bool: ...

    async def save_report(self, investigation_id: str, report: FullReport) -> None: ...
    async def save_cost_estimate(self, investigation_id: str, estimate: Optional[CostEstimate]) -> None: ...


@dataclass
class _Record:
    order: OrderInput
    state: InvestigationState
    events: List[ProgressEvent] = field(default_factory=list)
    facts: List[FactRow] = field(default_factory=list)
    evidence: List[EvidenceRow] = field(default_factory=list)
    questions: List[QuestionRow] = field(default_factory=list)
    report: Optional[FullReport] = None
    cost: Optional[CostEstimate] = None


class InMemoryStore:
    """Process-local store. Single event loop, so each method is atomic between awaits."""

    def __init__(self) -> None:
        self._records: Dict[str, _Record] = {}

    def create(self, investigation_id: str, order: OrderInput) -> None:
        self._records[investigation_id] = _Record(order=order, state=InvestigationState.CREATED)

    def _get(self, investigation_id: str) -> _Record:
        try:
            return self._records[investigation_id]
        except KeyError:
            raise LookupError(f"investigation {investigation_id} does not exist") from None

    async def get_state(self, investigation_id):
        rec = self._records.get(investigation_id)
        return rec.state if rec else None

    async def transition(self, investigation_id, from_state, to_state):
        rec = self._get(investigation_id)
        if rec.state != from_state:
            return False
        rec.state = to_state
        return True

    async def force_state(self, investigation_id, to_state):
        rec = self._get(investigation_id)
        if rec.state in TERMINAL:
            return None
        previous, rec.state = rec.state, to_state
        return previous

    async def get_order(self, investigation_id):
        rec = self._records.get(investigation_id)
        return rec.order if rec else None

    async def add_event(self, investigation_id, event):
        self._get(investigation_id).events.append(event)

    async def list_events(self, investigation_id):
        return list(self._get(investigation_id).events)

    async def save_facts(self, investigation_id, facts):
        rec = self._get(investigation_id)
        for fact in facts:
            rec.facts.append(FactRow(
                id=fact.id, investigation_id=investigation_id, field=fact.field, value=_fact_text(fact.value),
                kind=fact.kind, evidence_id=fact.evidence_id, confidence=fact.confidence))

    async def list_facts(self, investigation_id):
        return list(self._get(investigation_id).facts)

    async def save_evidence(self, investigation_id, items):
        rec = self._get(investigation_id)
        for item in items:
            rec.evidence.append(EvidenceRow(
                id=item.id, investigation_id=investigation_id, source_url=item.source_url,
                retrieved_at=item.retrieved_at, excerpt=item.excerpt, snapshot_ref=item.snapshot_ref,
                source_type=item.source_type))

    async def list_evidence(self, investigation_id):
        return list(self._get(investigation_id).evidence)

    async def save_question(self, investigation_id, question):
        self._get(investigation_id).questions.append(QuestionRow(
            id=question.id, investigation_id=investigation_id, field=question.field, prompt=question.prompt,
            why_it_matters=question.why_it_matters, answer=None, status=question.status,
            created_at=question.created_at))

    async def list_questions(self, investigation_id):
        return list(self._get(investigation_id).questions)

    async def resolve_question(self, investigation_id, question_id, answer, skipped):
        rec = self._get(investigation_id)
        for i, row in enumerate(rec.questions):
            if row.id == question_id:
                rec.questions[i] = row.model_copy(update={
                    "answer": None if skipped else answer,
                    "status": QUESTION_SKIPPED if skipped else QUESTION_ANSWERED})
                return True
        return False

    async def save_report(self, investigation_id, report):
        self._get(investigation_id).report = report

    async def save_cost_estimate(self, investigation_id, estimate):
        self._get(investigation_id).cost = estimate

    # Test and API helpers -------------------------------------------------

    def report(self, investigation_id: str) -> Optional[FullReport]:
        return self._get(investigation_id).report

    def cost(self, investigation_id: str) -> Optional[CostEstimate]:
        return self._get(investigation_id).cost


def _fact_text(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


__all__ = ["InMemoryStore", "InvestigationStore", "OrderInput", "ProgressEvent", "QUESTION_OPEN", "utcnow"]
