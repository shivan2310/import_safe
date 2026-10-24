"""Async repositories over asyncpg. See docs/decisions.md section 10.

Every function takes an asyncpg Pool or Connection. Money is stored as the text of a
Decimal (never float). Soft-deleted investigations, and everything under them, are never
returned. Input is validated before any query runs.
"""
import contextlib
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator, Dict, List, Optional, Sequence, Union

import asyncpg
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.db.ids import new_ulid, require_ulid
from app.decision.enums import Confidence, FactKind, Outcome, RiskLevel
from app.decision.report_schema import FactValue, SourceType

Executor = Union[asyncpg.Pool, asyncpg.Connection]
MoneyIn = Union[str, int, Decimal]

QUESTION_OPEN = "open"
QUESTION_ANSWERED = "answered"
QUESTION_SKIPPED = "skipped"
QUESTION_STATUSES = (QUESTION_OPEN, QUESTION_ANSWERED, QUESTION_SKIPPED)


class DuplicateIdError(ValueError):
    """A row with this ID already exists."""


class InvestigationNotFoundError(LookupError):
    """The investigation does not exist."""


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------

def money_text(value: Any) -> str:
    """A Decimal string for a TEXT money column. Floats and non-finite values are rejected."""
    if isinstance(value, (float, bool)) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("money must be a Decimal, int or str; floats are not allowed")
    try:
        number = Decimal(value) if isinstance(value, (str, int)) else value
    except InvalidOperation:
        raise ValueError("money is not a valid decimal number") from None
    if not number.is_finite():
        raise ValueError("money must be finite")
    return format(number, "f")


def _aware(value: Any, what: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{what} must be a timezone-aware datetime")
    return value


def _nonempty(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{what} must be a non-empty string")
    return value


def _fact_text(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) or not isinstance(value, (str, int, Decimal)):
        raise ValueError("fact value must be str, int, bool or Decimal; floats are not allowed")
    return str(value)


@contextlib.asynccontextmanager
async def _connection(executor: Executor) -> AsyncIterator[asyncpg.Connection]:
    if isinstance(executor, asyncpg.Pool):
        async with executor.acquire() as conn:
            yield conn
    else:
        yield executor


# ---------------------------------------------------------------------------
# Row models (returned by the readers)
# ---------------------------------------------------------------------------

class _Row(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Investigation(_Row):
    id: str
    url: str
    normalized_url: Optional[str]
    quantity: Optional[int]
    destination: Optional[Any]
    purpose: Optional[str]
    variant: Optional[str]
    status: str
    session_id: str
    created_at: datetime
    expires_at: Optional[datetime]


class FactRow(_Row):
    id: str
    investigation_id: str
    field: str
    value: str
    kind: FactKind
    evidence_id: Optional[str]
    confidence: Optional[Confidence]


class EvidenceRow(_Row):
    id: str
    investigation_id: str
    source_url: str
    retrieved_at: datetime
    excerpt: Optional[str]
    snapshot_ref: Optional[str]
    source_type: SourceType


class QuestionRow(_Row):
    id: str
    investigation_id: str
    field: str
    prompt: str
    why_it_matters: Optional[str]
    answer: Optional[str]
    status: str
    created_at: datetime


class ReportRow(_Row):
    investigation_id: str
    outcome: Outcome
    risk_level: RiskLevel
    score: int
    next_actions: List[Any]
    generated_at: datetime
    rule_set_versions: List[Any]
    report_json: Optional[Dict[str, Any]]


class CostEstimateRow(_Row):
    investigation_id: str
    assumptions: List[Any]
    breakdown: List[Any]
    low: str  # Decimal strings, exactly as stored
    expected: str
    high: str
    per_unit_expected: str


# ---------------------------------------------------------------------------
# Row inputs (validated before any query)
# ---------------------------------------------------------------------------

class _In(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class FactIn(_In):
    id: str = Field(default_factory=new_ulid)
    field: str
    value: FactValue  # strict types: a float is rejected, not coerced
    kind: FactKind
    evidence_id: Optional[str] = None
    confidence: Optional[Confidence] = None

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return require_ulid(v, "fact id")

    @field_validator("evidence_id")
    @classmethod
    def _evidence_id(cls, v: Optional[str]) -> Optional[str]:
        return None if v is None else require_ulid(v, "evidence_id")

    @field_validator("field")
    @classmethod
    def _field(cls, v: str) -> str:
        return _nonempty(v, "field")


class EvidenceIn(_In):
    id: str = Field(default_factory=new_ulid)
    source_url: str
    retrieved_at: datetime
    excerpt: Optional[str] = None
    snapshot_ref: Optional[str] = None
    source_type: SourceType

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return require_ulid(v, "evidence id")

    @field_validator("source_url")
    @classmethod
    def _url(cls, v: str) -> str:
        return _nonempty(v, "source_url")

    @field_validator("retrieved_at")
    @classmethod
    def _at(cls, v: datetime) -> datetime:
        return _aware(v, "retrieved_at")


class QuestionIn(_In):
    id: str = Field(default_factory=new_ulid)
    field: str
    prompt: str
    why_it_matters: Optional[str] = None
    status: str = QUESTION_OPEN
    created_at: datetime

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        return require_ulid(v, "question id")

    @field_validator("field", "prompt")
    @classmethod
    def _text(cls, v: str) -> str:
        return _nonempty(v, "field/prompt")

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        if v not in QUESTION_STATUSES:
            raise ValueError("question status must be one of: " + ", ".join(QUESTION_STATUSES))
        return v

    @field_validator("created_at")
    @classmethod
    def _at(cls, v: datetime) -> datetime:
        return _aware(v, "created_at")


# ---------------------------------------------------------------------------
# Investigations
# ---------------------------------------------------------------------------

_INVESTIGATION_COLUMNS = ("id, url, normalized_url, quantity, destination, purpose, variant, status, "
                          "session_id, created_at, expires_at")


def _investigation(record: asyncpg.Record) -> Investigation:
    return Investigation(**dict(record))


async def create_investigation(
    executor: Executor,
    *,
    url: str,
    session_id: str,
    status: str,
    created_at: datetime,
    expires_at: Optional[datetime] = None,
    id: Optional[str] = None,
    normalized_url: Optional[str] = None,
    quantity: Optional[int] = None,
    destination: Optional[Any] = None,
    purpose: Optional[str] = None,
    variant: Optional[str] = None,
) -> Investigation:
    inv_id = require_ulid(id, "investigation id") if id is not None else new_ulid()
    require_ulid(session_id, "session_id")
    _nonempty(url, "url")
    _nonempty(status, "status")
    _aware(created_at, "created_at")
    if expires_at is not None:
        _aware(expires_at, "expires_at")
    if quantity is not None and (isinstance(quantity, bool) or not isinstance(quantity, int) or quantity < 1):
        raise ValueError("quantity must be a positive integer")
    try:
        record = await executor.fetchrow(
            f"INSERT INTO investigations (id, url, normalized_url, quantity, destination, purpose, variant, "
            f"status, session_id, created_at, expires_at) "
            f"VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11) RETURNING {_INVESTIGATION_COLUMNS}",
            inv_id, url, normalized_url, quantity, destination, purpose, variant, status, session_id,
            created_at, expires_at,
        )
    except asyncpg.UniqueViolationError:
        raise DuplicateIdError(f"investigation {inv_id} already exists") from None
    return _investigation(record)


async def get_investigation(executor: Executor, investigation_id: str,
                            session_id: Optional[str] = None) -> Optional[Investigation]:
    """A live investigation, or None. With `session_id`, only if that session owns it."""
    require_ulid(investigation_id, "investigation id")
    if session_id is not None:
        require_ulid(session_id, "session_id")
    record = await executor.fetchrow(
        f"SELECT {_INVESTIGATION_COLUMNS} FROM investigations "
        f"WHERE id = $1 AND deleted_at IS NULL AND ($2::text IS NULL OR session_id = $2)",
        investigation_id, session_id,
    )
    return _investigation(record) if record is not None else None


async def update_investigation_status(executor: Executor, investigation_id: str, status: str) -> bool:
    require_ulid(investigation_id, "investigation id")
    _nonempty(status, "status")
    record = await executor.fetchrow(
        "UPDATE investigations SET status = $2 WHERE id = $1 AND deleted_at IS NULL RETURNING id",
        investigation_id, status,
    )
    return record is not None


async def soft_delete(executor: Executor, investigation_id: str, deleted_at: datetime) -> bool:
    """Hide an investigation (and its children) from every reader. Returns False if there was no live row."""
    require_ulid(investigation_id, "investigation id")
    _aware(deleted_at, "deleted_at")
    record = await executor.fetchrow(
        "UPDATE investigations SET deleted_at = $2 WHERE id = $1 AND deleted_at IS NULL RETURNING id",
        investigation_id, deleted_at,
    )
    return record is not None


async def hard_delete(executor: Executor, investigation_id: str) -> bool:
    """Remove the investigation and, by cascade, every related row. Works on soft-deleted rows too."""
    require_ulid(investigation_id, "investigation id")
    record = await executor.fetchrow("DELETE FROM investigations WHERE id = $1 RETURNING id", investigation_id)
    return record is not None


async def list_by_session(executor: Executor, session_id: str) -> List[Investigation]:
    require_ulid(session_id, "session_id")
    records = await executor.fetch(
        f"SELECT {_INVESTIGATION_COLUMNS} FROM investigations "
        f"WHERE session_id = $1 AND deleted_at IS NULL ORDER BY created_at DESC, id DESC",
        session_id,
    )
    return [_investigation(r) for r in records]


# ---------------------------------------------------------------------------
# Writers for child tables
# ---------------------------------------------------------------------------

async def _insert_many(executor: Executor, sql: str, rows: List[tuple], investigation_id: str, what: str) -> None:
    """All-or-nothing insert; maps constraint errors to repository errors."""
    if not rows:
        return
    try:
        async with _connection(executor) as conn:
            async with conn.transaction():
                await conn.executemany(sql, rows)
    except asyncpg.UniqueViolationError:
        raise DuplicateIdError(f"a {what} with one of these ids already exists") from None
    except asyncpg.ForeignKeyViolationError:
        raise InvestigationNotFoundError(f"investigation {investigation_id} does not exist") from None


async def save_facts(executor: Executor, investigation_id: str, facts: Sequence[FactIn]) -> List[str]:
    require_ulid(investigation_id, "investigation id")
    rows = [
        (f.id, investigation_id, f.field, _fact_text(f.value), f.kind.value, f.evidence_id,
         f.confidence.value if f.confidence else None)
        for f in facts
    ]
    await _insert_many(
        executor,
        "INSERT INTO facts (id, investigation_id, field, value, kind, evidence_id, confidence) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        rows, investigation_id, "fact",
    )
    return [f.id for f in facts]


async def save_evidence(executor: Executor, investigation_id: str, items: Sequence[EvidenceIn]) -> List[str]:
    require_ulid(investigation_id, "investigation id")
    rows = [(e.id, investigation_id, e.source_url, e.retrieved_at, e.excerpt, e.snapshot_ref, e.source_type)
            for e in items]
    await _insert_many(
        executor,
        "INSERT INTO evidence (id, investigation_id, source_url, retrieved_at, excerpt, snapshot_ref, source_type) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7)",
        rows, investigation_id, "evidence item",
    )
    return [e.id for e in items]


async def save_snapshot(executor: Executor, investigation_id: str, *, task_id: str, url: str, content: str,
                        retrieved_at: datetime, id: Optional[str] = None) -> str:
    """Store the raw page text of a retrieval. It is untrusted data and is only ever stored."""
    require_ulid(investigation_id, "investigation id")
    snapshot_id = require_ulid(id, "snapshot id") if id is not None else new_ulid()
    _nonempty(task_id, "task_id")
    _nonempty(url, "url")
    if not isinstance(content, str):
        raise ValueError("content must be a string")
    _aware(retrieved_at, "retrieved_at")
    await _insert_many(
        executor,
        "INSERT INTO raw_snapshots (id, investigation_id, task_id, url, content, retrieved_at) "
        "VALUES ($1, $2, $3, $4, $5, $6)",
        [(snapshot_id, investigation_id, task_id, url, content, retrieved_at)], investigation_id, "snapshot",
    )
    return snapshot_id


async def save_question(executor: Executor, investigation_id: str, question: QuestionIn) -> str:
    require_ulid(investigation_id, "investigation id")
    await _insert_many(
        executor,
        "INSERT INTO questions (id, investigation_id, field, prompt, why_it_matters, answer, status, created_at) "
        "VALUES ($1, $2, $3, $4, $5, NULL, $6, $7)",
        [(question.id, investigation_id, question.field, question.prompt, question.why_it_matters,
          question.status, question.created_at)],
        investigation_id, "question",
    )
    return question.id


async def update_question_answer(executor: Executor, investigation_id: str, question_id: str, answer: str) -> bool:
    require_ulid(investigation_id, "investigation id")
    require_ulid(question_id, "question id")
    _nonempty(answer, "answer")
    record = await executor.fetchrow(
        "UPDATE questions SET answer = $3, status = $4 WHERE id = $1 AND investigation_id = $2 RETURNING id",
        question_id, investigation_id, answer, QUESTION_ANSWERED,
    )
    return record is not None


async def save_report(
    executor: Executor,
    investigation_id: str,
    *,
    outcome: Outcome,
    risk_level: RiskLevel,
    score: int,
    next_actions: List[Any],
    generated_at: datetime,
    rule_set_versions: List[Any],
    report_json: Optional[Dict[str, Any]] = None,
) -> None:
    """Insert or replace the report. `report_json` is the full FullReport.to_frontend() snapshot."""
    require_ulid(investigation_id, "investigation id")
    outcome, risk_level = Outcome(outcome), RiskLevel(risk_level)
    if isinstance(score, bool) or not isinstance(score, int):
        raise ValueError("score must be an integer")
    _aware(generated_at, "generated_at")
    try:
        await executor.execute(
            "INSERT INTO reports (investigation_id, outcome, risk_level, score, next_actions, generated_at, "
            "rule_set_versions, report_json) VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
            "ON CONFLICT (investigation_id) DO UPDATE SET outcome = EXCLUDED.outcome, "
            "risk_level = EXCLUDED.risk_level, score = EXCLUDED.score, next_actions = EXCLUDED.next_actions, "
            "generated_at = EXCLUDED.generated_at, rule_set_versions = EXCLUDED.rule_set_versions, "
            "report_json = EXCLUDED.report_json",
            investigation_id, outcome.value, risk_level.value, score, next_actions, generated_at,
            rule_set_versions, report_json,
        )
    except asyncpg.ForeignKeyViolationError:
        raise InvestigationNotFoundError(f"investigation {investigation_id} does not exist") from None


async def save_cost_estimate(
    executor: Executor,
    investigation_id: str,
    *,
    assumptions: List[Any],
    breakdown: List[Any],
    low: MoneyIn,
    expected: MoneyIn,
    high: MoneyIn,
    per_unit_expected: MoneyIn,
) -> None:
    """Insert or replace the cost estimate. Money goes in as Decimal strings; JSON must hold no floats."""
    require_ulid(investigation_id, "investigation id")
    amounts = [money_text(v) for v in (low, expected, high, per_unit_expected)]
    from app.db.database import encode_jsonb  # validate before asyncpg sees them
    encode_jsonb(assumptions)
    encode_jsonb(breakdown)
    try:
        await executor.execute(
            "INSERT INTO cost_estimates (investigation_id, assumptions, breakdown, low, expected, high, "
            "per_unit_expected) VALUES ($1, $2, $3, $4, $5, $6, $7) "
            "ON CONFLICT (investigation_id) DO UPDATE SET assumptions = EXCLUDED.assumptions, "
            "breakdown = EXCLUDED.breakdown, low = EXCLUDED.low, expected = EXCLUDED.expected, "
            "high = EXCLUDED.high, per_unit_expected = EXCLUDED.per_unit_expected",
            investigation_id, assumptions, breakdown, *amounts,
        )
    except asyncpg.ForeignKeyViolationError:
        raise InvestigationNotFoundError(f"investigation {investigation_id} does not exist") from None


# ---------------------------------------------------------------------------
# Readers for child tables (nothing under a soft-deleted investigation is returned)
# ---------------------------------------------------------------------------

_LIVE = "EXISTS (SELECT 1 FROM investigations i WHERE i.id = {alias}.investigation_id AND i.deleted_at IS NULL)"


async def list_facts(executor: Executor, investigation_id: str) -> List[FactRow]:
    require_ulid(investigation_id, "investigation id")
    records = await executor.fetch(
        "SELECT id, investigation_id, field, value, kind, evidence_id, confidence FROM facts f "
        f"WHERE f.investigation_id = $1 AND {_LIVE.format(alias='f')} ORDER BY f.id",
        investigation_id,
    )
    return [FactRow(**dict(r)) for r in records]


async def list_evidence(executor: Executor, investigation_id: str) -> List[EvidenceRow]:
    require_ulid(investigation_id, "investigation id")
    records = await executor.fetch(
        "SELECT id, investigation_id, source_url, retrieved_at, excerpt, snapshot_ref, source_type FROM evidence e "
        f"WHERE e.investigation_id = $1 AND {_LIVE.format(alias='e')} ORDER BY e.id",
        investigation_id,
    )
    return [EvidenceRow(**dict(r)) for r in records]


async def list_questions(executor: Executor, investigation_id: str) -> List[QuestionRow]:
    require_ulid(investigation_id, "investigation id")
    records = await executor.fetch(
        "SELECT id, investigation_id, field, prompt, why_it_matters, answer, status, created_at FROM questions q "
        f"WHERE q.investigation_id = $1 AND {_LIVE.format(alias='q')} ORDER BY q.id",
        investigation_id,
    )
    return [QuestionRow(**dict(r)) for r in records]


async def get_report(executor: Executor, investigation_id: str) -> Optional[ReportRow]:
    require_ulid(investigation_id, "investigation id")
    record = await executor.fetchrow(
        "SELECT investigation_id, outcome, risk_level, score, next_actions, generated_at, rule_set_versions, "
        f"report_json FROM reports r WHERE r.investigation_id = $1 AND {_LIVE.format(alias='r')}",
        investigation_id,
    )
    return ReportRow(**dict(record)) if record is not None else None


async def get_cost_estimate(executor: Executor, investigation_id: str) -> Optional[CostEstimateRow]:
    require_ulid(investigation_id, "investigation id")
    record = await executor.fetchrow(
        "SELECT investigation_id, assumptions, breakdown, low, expected, high, per_unit_expected "
        f"FROM cost_estimates c WHERE c.investigation_id = $1 AND {_LIVE.format(alias='c')}",
        investigation_id,
    )
    return CostEstimateRow(**dict(record)) if record is not None else None


# ---------------------------------------------------------------------------
# Order inputs
# ---------------------------------------------------------------------------

async def save_order_input(
    executor: Executor,
    investigation_id: str,
    *,
    freight_inr: Optional[Any] = None,
    insurance_inr: Optional[Any] = None,
    url: Optional[str] = None,
    quantity: Optional[int] = None,
    purpose: Optional[str] = None,
    variant: Optional[str] = None,
    destination_state: Optional[str] = None,
    destination_city: Optional[str] = None,
    seller_certificates: Optional[Any] = None,
) -> None:
    """Persist the buyer's order inputs for later retrieval. Upserts."""
    require_ulid(investigation_id, "investigation id")
    shipping_amount = money_text(freight_inr) if freight_inr is not None else None
    insurance = money_text(insurance_inr) if insurance_inr is not None else None
    try:
        await executor.execute(
            "INSERT INTO order_inputs (investigation_id, shipping_amount, insurance) "
            "VALUES ($1, $2, $3) "
            "ON CONFLICT (investigation_id) DO UPDATE SET "
            "shipping_amount = EXCLUDED.shipping_amount, insurance = EXCLUDED.insurance",
            investigation_id, shipping_amount, insurance,
        )
    except asyncpg.ForeignKeyViolationError:
        raise InvestigationNotFoundError(f"investigation {investigation_id} does not exist") from None


# ---------------------------------------------------------------------------
# Progress events
# ---------------------------------------------------------------------------

async def add_progress_event(
    executor: Executor,
    investigation_id: str,
    *,
    stage: str,
    state: str,
    message: str,
    at: datetime,
) -> str:
    """Append a progress event. Returns the new event id."""
    require_ulid(investigation_id, "investigation id")
    _nonempty(stage, "stage")
    _nonempty(state, "state")
    _aware(at, "at")
    event_id = new_ulid()
    try:
        await executor.execute(
            "INSERT INTO progress_events (id, investigation_id, stage, state, message, at) "
            "VALUES ($1, $2, $3, $4, $5, $6)",
            event_id, investigation_id, stage, state, message, at,
        )
    except asyncpg.ForeignKeyViolationError:
        raise InvestigationNotFoundError(f"investigation {investigation_id} does not exist") from None
    return event_id


async def list_progress_events(executor: Executor, investigation_id: str) -> List[Dict[str, Any]]:
    """All events for an investigation in chronological order."""
    require_ulid(investigation_id, "investigation id")
    records = await executor.fetch(
        "SELECT stage, state, message, at FROM progress_events "
        "WHERE investigation_id = $1 ORDER BY at ASC, id ASC",
        investigation_id,
    )
    return [dict(r) for r in records]
