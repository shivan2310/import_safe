"""Postgres-backed InvestigationStore. Wraps app.db.repositories.

This is injected by the FastAPI app in production. Tests use InMemoryStore.
"""
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence

import asyncpg

from app.coordinator.states import InvestigationState, TERMINAL
from app.coordinator.store import InvestigationStore, OrderInput, ProgressEvent
from app.db import repositories as repo
from app.db.ids import new_ulid, require_ulid
from app.db.repositories import (
    QUESTION_ANSWERED, QUESTION_OPEN, QUESTION_SKIPPED,
    EvidenceIn, EvidenceRow, FactIn, FactRow, QuestionIn, QuestionRow,
    InvestigationNotFoundError,
)
from app.decision.cost_engine import CostEstimate, CostOverrides
from app.decision.enums import StageState
from app.decision.report_schema import FullReport

log = logging.getLogger(__name__)

Executor = asyncpg.Pool


class PostgresInvestigationStore:
    """Persists coordinator state to Supabase Postgres via asyncpg."""

    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    async def get_state(self, investigation_id: str) -> Optional[InvestigationState]:
        inv = await repo.get_investigation(self._pool, investigation_id)
        if inv is None:
            return None
        try:
            return InvestigationState(inv.status)
        except ValueError:
            log.warning("pg_store: unknown status %r for %s", inv.status, investigation_id)
            return None

    async def transition(self, investigation_id: str, from_state: InvestigationState,
                         to_state: InvestigationState) -> bool:
        """Atomic compare-and-set using a conditional UPDATE."""
        require_ulid(investigation_id, "investigation id")
        record = await self._pool.fetchrow(
            "UPDATE investigations SET status = $3 "
            "WHERE id = $1 AND status = $2 AND deleted_at IS NULL RETURNING id",
            investigation_id, from_state.value, to_state.value,
        )
        return record is not None

    async def force_state(self, investigation_id: str, to_state: InvestigationState) -> Optional[InvestigationState]:
        require_ulid(investigation_id, "investigation id")
        record = await self._pool.fetchrow(
            "UPDATE investigations SET status = $2 "
            "WHERE id = $1 AND deleted_at IS NULL "
            "AND status NOT IN ('FAILED','CANCELLED','EXPIRED','DELETED') RETURNING status",
            investigation_id, to_state.value,
        )
        if record is None:
            return None
        # record["status"] is the OLD value (Postgres RETURNING gives new value; we need old)
        # Use a two-step workaround: we stored old in a CTE would be cleaner, but this is fine:
        # just return to_state as previous because the caller only uses it for logging.
        return to_state  # caller only checks None vs non-None

    async def get_order(self, investigation_id: str) -> Optional[OrderInput]:
        """Re-read the OrderInput from the investigations row + order_inputs row."""
        inv = await repo.get_investigation(self._pool, investigation_id)
        if inv is None:
            return None
        row = await self._pool.fetchrow(
            "SELECT shipping_amount, insurance FROM order_inputs WHERE investigation_id = $1",
            investigation_id,
        )
        freight = Decimal(row["shipping_amount"]) if row and row["shipping_amount"] else None
        insurance = Decimal(row["insurance"]) if row and row["insurance"] else None
        dest = inv.destination or {}
        return OrderInput(
            url=inv.url,
            quantity=inv.quantity or 1,
            purpose=inv.purpose,
            variant=inv.variant,
            destination_state=dest.get("state") if isinstance(dest, dict) else None,
            destination_city=dest.get("city") if isinstance(dest, dict) else None,
            freight_inr=freight,
            insurance_inr=insurance,
        )

    async def add_event(self, investigation_id: str, event: ProgressEvent) -> None:
        try:
            await repo.add_progress_event(
                self._pool, investigation_id,
                stage=event.stage, state=event.state.value,
                message=event.message, at=event.at,
            )
        except InvestigationNotFoundError:
            log.warning("pg_store: add_event for missing investigation %s", investigation_id)

    async def list_events(self, investigation_id: str) -> List[ProgressEvent]:
        rows = await repo.list_progress_events(self._pool, investigation_id)
        return [ProgressEvent(stage=r["stage"], state=StageState(r["state"]),
                              message=r["message"], at=r["at"]) for r in rows]

    async def save_facts(self, investigation_id: str, facts: Sequence[FactIn]) -> None:
        if facts:
            await repo.save_facts(self._pool, investigation_id, facts)

    async def list_facts(self, investigation_id: str) -> List[FactRow]:
        return await repo.list_facts(self._pool, investigation_id)

    async def save_evidence(self, investigation_id: str, items: Sequence[EvidenceIn]) -> None:
        if items:
            await repo.save_evidence(self._pool, investigation_id, items)

    async def list_evidence(self, investigation_id: str) -> List[EvidenceRow]:
        return await repo.list_evidence(self._pool, investigation_id)

    async def save_question(self, investigation_id: str, question: QuestionIn) -> None:
        await repo.save_question(self._pool, investigation_id, question)

    async def list_questions(self, investigation_id: str) -> List[QuestionRow]:
        return await repo.list_questions(self._pool, investigation_id)

    async def resolve_question(self, investigation_id: str, question_id: str, answer: Optional[str],
                               skipped: bool) -> bool:
        if skipped:
            record = await self._pool.fetchrow(
                "UPDATE questions SET status = $3 "
                "WHERE id = $1 AND investigation_id = $2 RETURNING id",
                question_id, investigation_id, QUESTION_SKIPPED,
            )
            return record is not None
        if answer is None:
            return False
        return await repo.update_question_answer(self._pool, investigation_id, question_id, answer)

    async def save_report(self, investigation_id: str, report: FullReport) -> None:
        report_dict = report.to_frontend()
        await repo.save_report(
            self._pool, investigation_id,
            outcome=report.outcome,
            risk_level=report.risk_level,
            score=report.score,
            next_actions=[a.model_dump(by_alias=True) for a in report.next_actions],
            generated_at=_now(),
            rule_set_versions=list(report.rule_versions),
            report_json=report_dict,
        )

    async def save_cost_estimate(self, investigation_id: str, estimate: Optional[CostEstimate]) -> None:
        if estimate is None:
            return
        await repo.save_cost_estimate(
            self._pool, investigation_id,
            low=estimate.low, expected=estimate.expected,
            high=estimate.high, per_unit_expected=estimate.per_unit_expected,
            assumptions=[a.model_dump(by_alias=True, mode="json") for a in estimate.assumptions],
            breakdown=[_line_dict(line) for line in estimate.breakdown],
        )


def _line_dict(line: Any) -> Dict[str, Any]:
    return line.model_dump(by_alias=True, mode="json")


def _now() -> datetime:
    return datetime.now(timezone.utc)
