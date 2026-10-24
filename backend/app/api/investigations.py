"""Investigation API — /api/investigations (docs/prd-backend.md B3).

All seven endpoints. The coordinator is driven as a FastAPI BackgroundTask so the POST
returns immediately with 201 while the investigation runs in the background.

Dependency injection:
    ``get_store()`` — returns an InvestigationStore (InMemoryStore in tests, Postgres in production).
    ``get_connector()`` — returns a TinyFishConnector.

Both can be overridden in tests with ``app.dependency_overrides``.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.api.rate_limit import RateLimiter, get_limiter
from app.coordinator.coordinator import recalculate_cost, run
from app.coordinator.states import InvestigationState, stage_progress
from app.coordinator.store import InMemoryStore, InvestigationStore, OrderInput
from app.db.ids import new_ulid
from app.db.repositories import QUESTION_OPEN
from app.db.session import resolve_session, sign_session, cookie_attributes, COOKIE_NAME
from app.decision.cost_engine import CostOverrides
from app.errors import ImportSafeError
from app.services.extraction.urls import validate_product_url
from app.services.tinyfish.fixture_adapter import FixtureTinyFishConnector

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/investigations", tags=["investigations"])

# ---------------------------------------------------------------------------
# Application-level singletons (overridden in tests via dependency_overrides)
# ---------------------------------------------------------------------------

_store: InMemoryStore = InMemoryStore()
_connector: FixtureTinyFishConnector = FixtureTinyFishConnector()


def get_store() -> InvestigationStore:
    return _store


def get_connector():
    return _connector


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class _Destination(BaseModel):
    model_config = ConfigDict(extra="ignore")
    state: Optional[str] = None
    city: Optional[str] = None


class _Shipping(BaseModel):
    model_config = ConfigDict(extra="ignore")
    amount: Optional[Any] = None
    currency: Optional[str] = None
    mode: Optional[str] = None


class CreateInvestigationRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str
    quantity: int = Field(ge=1)
    destination: Optional[_Destination] = None
    purpose: Optional[str] = None
    variant: Optional[str] = None
    shipping: Optional[_Shipping] = None
    sellerCertificates: Optional[List[str]] = None

    @field_validator("url")
    @classmethod
    def _url(cls, v: str) -> str:
        try:
            return validate_product_url(v)
        except Exception as exc:
            raise ValueError(str(exc)) from exc


class AnswerRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    questionId: str
    value: Optional[str] = None
    skipped: bool = False

    @model_validator(mode="after")
    def _check(self) -> "AnswerRequest":
        if not self.skipped and (self.value is None or not self.value.strip()):
            raise ValueError("value is required when skipped is false")
        return self


class AssumptionsRequest(BaseModel):
    """All fields are optional; only the ones provided are applied as overrides."""
    model_config = ConfigDict(extra="ignore")
    freightInr: Optional[str] = None
    fxUsdInr: Optional[str] = None
    bcdPct: Optional[str] = None
    igstPct: Optional[str] = None
    clearingInr: Optional[str] = None

    def to_overrides(self) -> Optional[CostOverrides]:
        def _d(v: Optional[str]) -> Optional[Decimal]:
            if v is None:
                return None
            try:
                return Decimal(v)
            except InvalidOperation:
                return None
        kwargs = {
            "fx_usd_inr": _d(self.fxUsdInr),
            "bcd_pct": _d(self.bcdPct),
            "igst_pct": _d(self.igstPct),
            "clearing_inr": _d(self.clearingInr),
        }
        if all(v is None for v in kwargs.values()):
            return None
        return CostOverrides(**{k: v for k, v in kwargs.items() if v is not None})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _freight(shipping: Optional[_Shipping]) -> Optional[Decimal]:
    if shipping is None or shipping.amount is None:
        return None
    try:
        return Decimal(str(shipping.amount))
    except (InvalidOperation, TypeError):
        return None


def _pending_question(questions) -> Optional[Dict[str, Any]]:
    for q in questions:
        if q.status == QUESTION_OPEN:
            return {"id": q.id, "field": q.field, "prompt": q.prompt,
                    "whyItMatters": q.why_it_matters}
    return None


def _session_from_request(request: Request, secret: Optional[str] = None):
    cookie = request.cookies.get(COOKIE_NAME)
    return resolve_session(cookie, secret)


def _set_session_cookie(response: Response, session_id: str, secret: Optional[str] = None) -> None:
    signed = sign_session(session_id, secret)
    attrs = cookie_attributes(max_age_s=30 * 24 * 3600, secure=False)  # secure=True in prod
    response.set_cookie(COOKIE_NAME, signed, **attrs)


# ---------------------------------------------------------------------------
# POST /api/investigations
# ---------------------------------------------------------------------------

@router.post("", status_code=201)
async def create_investigation(
    req: CreateInvestigationRequest,
    background_tasks: BackgroundTasks,
    response: Response,
    request: Request,
    store: InvestigationStore = Depends(get_store),
    connector=Depends(get_connector),
    limiter: RateLimiter = Depends(get_limiter),
):
    client_ip = request.client.host if request.client else "unknown"
    limiter.check(client_ip)
    session_id, is_new = _session_from_request(request)
    inv_id = new_ulid()
    freight = _freight(req.shipping)
    order = OrderInput(
        url=req.url,
        quantity=req.quantity,
        purpose=req.purpose,
        variant=req.variant,
        destination_state=req.destination.state if req.destination else None,
        destination_city=req.destination.city if req.destination else None,
        freight_inr=freight,
        seller_certificates=tuple(req.sellerCertificates or []),
    )
    if isinstance(store, InMemoryStore):
        store.create(inv_id, order)
    else:
        # Postgres store: create the investigation row first, then start the coordinator.
        from app.db.repositories import create_investigation as db_create
        pool = store._pool
        await db_create(pool, id=inv_id, url=req.url, session_id=session_id,
                        status=InvestigationState.CREATED.value, created_at=_now(),
                        quantity=req.quantity, purpose=req.purpose, variant=req.variant,
                        destination={"state": order.destination_state, "city": order.destination_city})
        from app.db.repositories import save_order_input
        await save_order_input(pool, inv_id, freight_inr=freight)
    if is_new:
        _set_session_cookie(response, session_id)
    background_tasks.add_task(_run_safe, inv_id, store, connector)
    return {"id": inv_id, "status": InvestigationState.CREATED.value}


async def _run_safe(inv_id: str, store: InvestigationStore, connector) -> None:
    try:
        await run(inv_id, store, connector)
    except Exception:
        log.exception("background run failed for %s", inv_id)


# ---------------------------------------------------------------------------
# GET /api/investigations/{id}
# ---------------------------------------------------------------------------

@router.get("/{investigation_id}")
async def get_investigation(
    investigation_id: str,
    store: InvestigationStore = Depends(get_store),
):
    state = await store.get_state(investigation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    questions = await store.list_questions(investigation_id)
    events = await store.list_events(investigation_id)
    stages = stage_progress(state)
    return {
        "id": investigation_id,
        "status": state.value,
        "stages": [{"stage": s, "state": st.value} for s, st in stages],
        "pendingQuestion": _pending_question(questions),
        "eventCount": len(events),
    }


# ---------------------------------------------------------------------------
# GET /api/investigations/{id}/events  (SSE or JSON poll)
# ---------------------------------------------------------------------------

@router.get("/{investigation_id}/events")
async def get_events(
    investigation_id: str,
    request: Request,
    store: InvestigationStore = Depends(get_store),
):
    """Server-sent events stream of progress events.

    If the client does not accept ``text/event-stream``, returns JSON instead (for polling).
    The stream sends all stored events then closes; the client reconnects to poll again.
    """
    accept = request.headers.get("accept", "")
    events = await store.list_events(investigation_id)
    if not events:
        state = await store.get_state(investigation_id)
        if state is None:
            raise HTTPException(status_code=404, detail="Investigation not found")

    if "text/event-stream" not in accept:
        return [{"stage": e.stage, "state": e.state.value, "message": e.message,
                 "at": e.at.isoformat()} for e in events]

    async def _stream() -> AsyncIterator[str]:
        for event in events:
            data = json.dumps({"stage": event.stage, "state": event.state.value,
                               "message": event.message, "at": event.at.isoformat()})
            yield f"data: {data}\n\n"
        yield "data: {\"done\": true}\n\n"

    return StreamingResponse(_stream(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ---------------------------------------------------------------------------
# POST /api/investigations/{id}/answers
# ---------------------------------------------------------------------------

@router.post("/{investigation_id}/answers", status_code=200)
async def post_answer(
    investigation_id: str,
    req: AnswerRequest,
    background_tasks: BackgroundTasks,
    store: InvestigationStore = Depends(get_store),
    connector=Depends(get_connector),
):
    state = await store.get_state(investigation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    ok = await store.resolve_question(investigation_id, req.questionId,
                                       req.value, req.skipped)
    if not ok:
        raise HTTPException(status_code=404, detail="Question not found")
    # Resume the investigation in the background if it is paused.
    if state == InvestigationState.NEEDS_INPUT:
        await store.force_state(investigation_id, InvestigationState.PROFILE_BUILT)
        background_tasks.add_task(_run_safe, investigation_id, store, connector)
    return {"ok": True}


# ---------------------------------------------------------------------------
# PATCH /api/investigations/{id}/assumptions
# ---------------------------------------------------------------------------

@router.patch("/{investigation_id}/assumptions", status_code=200)
async def patch_assumptions(
    investigation_id: str,
    req: AssumptionsRequest,
    background_tasks: BackgroundTasks,
    store: InvestigationStore = Depends(get_store),
):
    state = await store.get_state(investigation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    overrides = req.to_overrides()
    background_tasks.add_task(_recalc_safe, investigation_id, store, overrides)
    return {"ok": True, "recalculating": True}


async def _recalc_safe(inv_id: str, store: InvestigationStore, overrides) -> None:
    try:
        await recalculate_cost(inv_id, store, overrides)
    except Exception:
        log.exception("recalculate_cost failed for %s", inv_id)


# ---------------------------------------------------------------------------
# GET /api/investigations/{id}/report
# ---------------------------------------------------------------------------

@router.get("/{investigation_id}/report")
async def get_report(
    investigation_id: str,
    store: InvestigationStore = Depends(get_store),
):
    state = await store.get_state(investigation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if state != InvestigationState.REPORT_READY:
        raise HTTPException(status_code=425, detail={"code": "not_ready", "status": state.value})
    if isinstance(store, InMemoryStore):
        report = store.report(investigation_id)
    else:
        from app.db.repositories import get_report
        pool = store._pool
        row = await get_report(pool, investigation_id)
        report_dict = row.report_json if row else None
        if report_dict is None:
            raise HTTPException(status_code=425, detail={"code": "not_ready", "status": state.value})
        return report_dict
    if report is None:
        raise HTTPException(status_code=425, detail={"code": "not_ready", "status": state.value})
    return report.to_frontend()


# ---------------------------------------------------------------------------
# DELETE /api/investigations/{id}
# ---------------------------------------------------------------------------

@router.delete("/{investigation_id}", status_code=200)
async def delete_investigation(
    investigation_id: str,
    store: InvestigationStore = Depends(get_store),
):
    state = await store.get_state(investigation_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if isinstance(store, InMemoryStore):
        # InMemoryStore: just mark deleted.
        await store.force_state(investigation_id, InvestigationState.DELETED)
    else:
        from app.db.repositories import hard_delete
        deleted = await hard_delete(store._pool, investigation_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Investigation not found")
    return {"ok": True, "deleted": investigation_id}
