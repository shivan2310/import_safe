"""Tests for the /api/investigations endpoints (Step 9).

All tests use TestClient with InMemoryStore and a FixtureTinyFishConnector injected via
FastAPI's dependency_overrides. No database or TinyFish network calls are made.

The coordinator's background task is run inline (synchronously after the response) via
``_run_safe`` called directly in tests, because TestClient does not await background tasks.
"""
import asyncio
import os
from datetime import datetime, timezone
from typing import Optional

import pytest
from fastapi.testclient import TestClient

import app.api.investigations as inv_module
from app.api.investigations import get_connector, get_store
from app.api.rate_limit import RateLimiter, get_limiter
from app.coordinator.coordinator import run as coord_run
from app.coordinator.states import InvestigationState as S
from app.coordinator.store import InMemoryStore
from app.main import app
from app.services.tinyfish.fixture_adapter import BT100_SOURCE_URL, FixtureTinyFishConnector
from app.services.tinyfish.models import ExtractionResult

# Ensure SESSION_KEY is set for tests so cookie helpers don't raise.
os.environ.setdefault("SECRET_KEY", "test-secret-key-for-importsafe-unit-tests-123456")

# ---------------------------------------------------------------------------
# Per-test store and connector via dependency_overrides
# ---------------------------------------------------------------------------

class _Ctx:
    """Holds one test's store and connector so tests can inspect them."""
    def __init__(self):
        self.store = InMemoryStore()
        self.connector = FixtureTinyFishConnector()


@pytest.fixture()
def ctx():
    c = _Ctx()
    _generous = RateLimiter(max_requests=10000, window_s=3600.0)
    app.dependency_overrides[get_store] = lambda: c.store
    app.dependency_overrides[get_connector] = lambda: c.connector
    app.dependency_overrides[get_limiter] = lambda: _generous
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def client(ctx):
    with TestClient(app, raise_server_exceptions=True) as c:
        yield c


def _run(inv_id: str, ctx: _Ctx) -> None:
    """Drive the investigation to completion synchronously (inline, no background task)."""
    asyncio.run(coord_run(inv_id, ctx.store, ctx.connector))


def _post_investigation(client, **overrides) -> dict:
    body = {"url": BT100_SOURCE_URL, "quantity": 100, "purpose": "resale", **overrides}
    resp = client.post("/api/investigations", json=body)
    assert resp.status_code == 201
    return resp.json()


# ---------------------------------------------------------------------------
# POST /api/investigations
# ---------------------------------------------------------------------------

class TestCreateInvestigation:
    def test_returns_201_and_id(self, client, ctx):
        data = _post_investigation(client)
        assert "id" in data
        assert data["status"] == "CREATED"

    def test_invalid_url_returns_422(self, client, ctx):
        resp = client.post("/api/investigations", json={"url": "http://127.0.0.1/evil", "quantity": 1})
        assert resp.status_code == 422

    def test_internal_url_returns_422(self, client, ctx):
        resp = client.post("/api/investigations", json={"url": "http://localhost/product", "quantity": 1})
        assert resp.status_code == 422

    def test_missing_quantity_returns_422(self, client, ctx):
        resp = client.post("/api/investigations", json={"url": BT100_SOURCE_URL})
        assert resp.status_code == 422

    def test_zero_quantity_returns_422(self, client, ctx):
        resp = client.post("/api/investigations", json={"url": BT100_SOURCE_URL, "quantity": 0})
        assert resp.status_code == 422

    def test_session_cookie_set(self, client, ctx):
        resp = client.post("/api/investigations", json={"url": BT100_SOURCE_URL, "quantity": 1})
        assert resp.status_code == 201
        assert "importsafe_session" in resp.cookies

    def test_investigation_created_in_store(self, client, ctx):
        data = _post_investigation(client)
        state = asyncio.run(ctx.store.get_state(data["id"]))
        assert state is not None


# ---------------------------------------------------------------------------
# GET /api/investigations/{id}
# ---------------------------------------------------------------------------

class TestGetInvestigation:
    def test_404_for_unknown(self, client, ctx):
        resp = client.get("/api/investigations/01NONEXISTENTINVESTIGATION1")
        assert resp.status_code == 404

    def test_returns_status_and_stages(self, client, ctx):
        data = _post_investigation(client)
        _run(data["id"], ctx)
        resp = client.get(f"/api/investigations/{data['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["id"] == data["id"]
        assert "stages" in body
        assert isinstance(body["stages"], list)

    def test_pending_question_when_listing_fails(self, client, ctx):
        bad_connector = FixtureTinyFishConnector()
        async def _fail(url):
            return ExtractionResult(source_url=url, retrieved_at=datetime.now(timezone.utc),
                                    status="FAILED", failed=True)
        bad_connector.extract_listing = _fail
        ctx.connector = bad_connector
        app.dependency_overrides[get_connector] = lambda: bad_connector
        data = _post_investigation(client)
        asyncio.run(coord_run(data["id"], ctx.store, bad_connector))
        resp = client.get(f"/api/investigations/{data['id']}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == S.NEEDS_INPUT.value
        assert body["pendingQuestion"] is not None


# ---------------------------------------------------------------------------
# GET /api/investigations/{id}/events
# ---------------------------------------------------------------------------

class TestGetEvents:
    def test_returns_list(self, client, ctx):
        data = _post_investigation(client)
        _run(data["id"], ctx)
        resp = client.get(f"/api/investigations/{data['id']}/events")
        assert resp.status_code == 200
        body = resp.json()
        assert isinstance(body, list)
        stages = [e["stage"] for e in body]
        assert "READING_LISTING" in stages

    def test_events_have_required_fields(self, client, ctx):
        data = _post_investigation(client)
        _run(data["id"], ctx)
        body = client.get(f"/api/investigations/{data['id']}/events").json()
        for event in body:
            assert "stage" in event
            assert "state" in event
            assert "message" in event
            assert "at" in event


# ---------------------------------------------------------------------------
# POST /api/investigations/{id}/answers
# ---------------------------------------------------------------------------

def _pause_for_question(client, ctx) -> tuple:
    """Create an investigation that pauses with a listing question, return (inv_id, question_id)."""
    bad_connector = FixtureTinyFishConnector()
    async def _fail(url):
        return ExtractionResult(source_url=url, retrieved_at=datetime.now(timezone.utc),
                                status="FAILED", failed=True)
    bad_connector.extract_listing = _fail
    app.dependency_overrides[get_connector] = lambda: bad_connector
    data = _post_investigation(client)
    asyncio.run(coord_run(data["id"], ctx.store, bad_connector))
    questions = asyncio.run(ctx.store.list_questions(data["id"]))
    return data["id"], questions[0].id


class TestPostAnswer:
    def test_skip_question(self, client, ctx):
        inv_id, question_id = _pause_for_question(client, ctx)
        resp = client.post(f"/api/investigations/{inv_id}/answers",
                           json={"questionId": question_id, "skipped": True})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_answer_question(self, client, ctx):
        inv_id, question_id = _pause_for_question(client, ctx)
        resp = client.post(f"/api/investigations/{inv_id}/answers",
                           json={"questionId": question_id, "value": "bluetooth speaker"})
        assert resp.status_code == 200

    def test_404_for_unknown_question(self, client, ctx):
        data = _post_investigation(client)
        _run(data["id"], ctx)
        resp = client.post(f"/api/investigations/{data['id']}/answers",
                           json={"questionId": "01NONEXISTENTQUESTION1111111", "value": "x"})
        assert resp.status_code == 404

    def test_value_required_when_not_skipped(self, client, ctx):
        data = _post_investigation(client)
        resp = client.post(f"/api/investigations/{data['id']}/answers",
                           json={"questionId": "someId", "skipped": False})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# PATCH /api/investigations/{id}/assumptions
# ---------------------------------------------------------------------------

class TestPatchAssumptions:
    def test_returns_ok(self, client, ctx):
        data = _post_investigation(client)
        _run(data["id"], ctx)
        resp = client.patch(f"/api/investigations/{data['id']}/assumptions",
                            json={"freightInr": "15000"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_404_for_unknown(self, client, ctx):
        resp = client.patch("/api/investigations/01NONEXISTENTINVESTIGATION1/assumptions",
                            json={"freightInr": "15000"})
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# GET /api/investigations/{id}/report
# ---------------------------------------------------------------------------

class TestGetReport:
    def test_report_returned_when_ready(self, client, ctx):
        data = _post_investigation(client)
        _run(data["id"], ctx)
        resp = client.get(f"/api/investigations/{data['id']}/report")
        assert resp.status_code == 200
        body = resp.json()
        assert "outcome" in body
        assert "disclaimer" in body

    def test_425_when_not_ready(self, client, ctx):
        # Create an investigation but block the background task by injecting a slow connector.
        # Instead of timing out, we just verify the status code semantics using InMemoryStore directly.
        store = ctx.store
        from app.db.ids import new_ulid
        from app.coordinator.store import OrderInput
        from decimal import Decimal
        inv_id = new_ulid()
        store.create(inv_id, OrderInput(url=BT100_SOURCE_URL, quantity=1))
        # State is CREATED, not REPORT_READY — report endpoint must return 425.
        resp = client.get(f"/api/investigations/{inv_id}/report")
        assert resp.status_code == 425

    def test_404_for_unknown(self, client, ctx):
        resp = client.get("/api/investigations/01NONEXISTENTINVESTIGATION1/report")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# DELETE /api/investigations/{id}
# ---------------------------------------------------------------------------

class TestDeleteInvestigation:
    def test_delete_returns_ok(self, client, ctx):
        data = _post_investigation(client)
        resp = client.delete(f"/api/investigations/{data['id']}")
        assert resp.status_code == 200
        assert resp.json()["deleted"] == data["id"]

    def test_get_after_delete_returns_deleted_state(self, client, ctx):
        data = _post_investigation(client)
        client.delete(f"/api/investigations/{data['id']}")
        resp = client.get(f"/api/investigations/{data['id']}")
        # InMemoryStore marks as DELETED; get_state returns DELETED not None.
        if resp.status_code == 200:
            assert resp.json()["status"] == S.DELETED.value
        else:
            assert resp.status_code == 404

    def test_404_for_unknown(self, client, ctx):
        resp = client.delete("/api/investigations/01NONEXISTENTINVESTIGATION1")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Existing routes still work
# ---------------------------------------------------------------------------

class TestExistingRoutes:
    def test_health(self, client, ctx):
        assert client.get("/health").status_code == 200
