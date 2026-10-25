"""Tests for POST /api/products/similar.

All tests use FixtureTinyFishConnector and InMemoryStore injected via dependency_overrides.
No real TinyFish calls are made.
"""
import asyncio
import os
from typing import Any, Dict, List, Optional, Tuple

import pytest
from fastapi.testclient import TestClient

from app.api.investigations import get_connector, get_store
from app.api.products import router as products_router, _mem_cache
from app.coordinator.store import InMemoryStore
from app.main import app
from app.services.tinyfish.fixture_adapter import FIXTURE_SIMILAR_PRODUCTS, FixtureTinyFishConnector

os.environ.setdefault("SECRET_KEY", "test-secret-for-products-tests")

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

class _NoSearchConnector(FixtureTinyFishConnector):
    """Connector that has no search_products method at all."""
    # Remove search_products by not defining it — inherited but we override to raise
    async def search_products(self, product_name: str, specs=None) -> Tuple[List[Dict], str]:
        raise AttributeError("should not be called")


class _EmptySearchConnector(FixtureTinyFishConnector):
    """Connector that returns empty results (live, no products found)."""
    async def search_products(self, product_name: str, specs=None) -> Tuple[List[Dict], str]:
        return [], "empty"


class _LiveSearchConnector(FixtureTinyFishConnector):
    """Connector that returns realistic live products."""
    async def search_products(self, product_name: str, specs=None) -> Tuple[List[Dict], str]:
        return [
            {
                "name": "Wireless Portable Speaker SX-10",
                "price": "9.50 - 14.00",
                "currency": "USD",
                "moq": "100 pieces",
                "seller": "Shenzhen Sound Tech Co.",
                "origin": "China",
                "sourceUrl": "https://www.alibaba.com/product-detail/sx-10.html",
            },
            {
                "name": "Compact BT Audio Speaker M3",
                "price": "6.00",
                "currency": "USD",
                "moq": "200 pieces",
                "seller": "Guangdong Audio Exports Ltd.",
                "origin": "China",
            },
        ], "live"


class _DuplicateSearchConnector(FixtureTinyFishConnector):
    """Returns duplicate product names."""
    async def search_products(self, product_name: str, specs=None) -> Tuple[List[Dict], str]:
        return [
            {"name": "Same Speaker", "price": "10.00", "currency": "USD", "seller": "A"},
            {"name": "Same Speaker", "price": "11.00", "currency": "USD", "seller": "B"},
            {"name": "Different Speaker", "price": "8.00", "currency": "USD", "seller": "C"},
        ], "live"


class _MalformedSearchConnector(FixtureTinyFishConnector):
    """Returns malformed / unusable results."""
    async def search_products(self, product_name: str, specs=None) -> Tuple[List[Dict], str]:
        return [
            None,                         # not a dict
            {},                           # no name
            {"name": "", "price": "5"},   # blank name
            "not a dict",                 # string instead of dict
        ], "live"


@pytest.fixture(autouse=True)
def _clear_mem_cache():
    """Clear the in-memory cache between tests."""
    _mem_cache.clear()
    yield
    _mem_cache.clear()


@pytest.fixture()
def client_with(request):
    """Parametrize test clients by connector class."""
    connector_cls = request.param if hasattr(request, 'param') else FixtureTinyFishConnector
    store = InMemoryStore()
    connector = connector_cls()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_connector] = lambda: connector
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def fixture_client():
    store = InMemoryStore()
    connector = FixtureTinyFishConnector()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_connector] = lambda: connector
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def live_client():
    store = InMemoryStore()
    connector = _LiveSearchConnector()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_connector] = lambda: connector
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def empty_client():
    store = InMemoryStore()
    connector = _EmptySearchConnector()
    app.dependency_overrides[get_store] = lambda: store
    app.dependency_overrides[get_connector] = lambda: connector
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Basic contract
# ---------------------------------------------------------------------------

class TestSimilarProductsBasic:
    def test_returns_200_with_fixture_connector(self, fixture_client):
        resp = fixture_client.post("/api/products/similar", json={"productName": "Bluetooth Speaker"})
        assert resp.status_code == 200

    def test_response_has_required_fields(self, fixture_client):
        body = fixture_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        assert "products" in body
        assert "dataSource" in body
        assert "isFixture" in body
        assert "disclaimer" in body

    def test_fixture_products_have_correct_structure(self, fixture_client):
        body = fixture_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        for product in body["products"]:
            assert "id" in product
            assert "name" in product
            assert "seller" in product
            assert "matchReasons" in product
            assert "isFixture" in product
            assert product["seller"]["verificationStatus"] in ("marketplace_listed", "fixture", "unverified")

    def test_fixture_data_source(self, fixture_client):
        body = fixture_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        assert body["dataSource"] == "fixture"
        assert body["isFixture"] is True

    def test_422_for_blank_product_name(self, fixture_client):
        resp = fixture_client.post("/api/products/similar", json={"productName": "   "})
        assert resp.status_code in (422, 400)

    def test_422_for_missing_product_name(self, fixture_client):
        resp = fixture_client.post("/api/products/similar", json={})
        assert resp.status_code == 422

    def test_accepts_optional_specs(self, fixture_client):
        resp = fixture_client.post("/api/products/similar", json={
            "productName": "Bluetooth Speaker",
            "specs": {"power": "10W", "battery": "2000mAh"},
        })
        assert resp.status_code == 200

    def test_accepts_optional_investigation_id(self, fixture_client):
        resp = fixture_client.post("/api/products/similar", json={
            "productName": "Speaker",
            "investigationId": "01ABCDEFGHIJKLMNOPQRSTUV",
        })
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Fixture data — never presented as genuine discovery
# ---------------------------------------------------------------------------

class TestFixtureDataIntegrity:
    def test_fixture_products_are_marked_as_fixture(self, fixture_client):
        body = fixture_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        assert body["isFixture"] is True
        for p in body["products"]:
            assert p["isFixture"] is True
            assert p["seller"]["verificationStatus"] == "fixture"

    def test_fixture_products_names_contain_fixture_marker(self, fixture_client):
        body = fixture_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        # All fixture product names start with [FIXTURE] (as defined in fixture_adapter.py)
        for p in body["products"]:
            assert "[FIXTURE]" in p["name"], f"Expected [FIXTURE] in '{p['name']}'"

    def test_fixture_is_not_live(self, fixture_client):
        body = fixture_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        assert body["dataSource"] != "live"


# ---------------------------------------------------------------------------
# Live results
# ---------------------------------------------------------------------------

class TestLiveResults:
    def test_live_results_not_marked_as_fixture(self, live_client):
        body = live_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        assert body["dataSource"] == "live"
        assert body["isFixture"] is False
        for p in body["products"]:
            assert p["isFixture"] is False

    def test_live_verification_status_is_marketplace_listed(self, live_client):
        body = live_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        for p in body["products"]:
            assert p["seller"]["verificationStatus"] == "marketplace_listed"

    def test_live_products_include_fields(self, live_client):
        body = live_client.post("/api/products/similar", json={"productName": "Wireless Speaker"}).json()
        assert len(body["products"]) >= 1
        first = body["products"][0]
        assert first["name"]
        assert first["seller"]["name"]

    def test_at_most_five_results(self, live_client):
        body = live_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        assert len(body["products"]) <= 5


# ---------------------------------------------------------------------------
# Empty results
# ---------------------------------------------------------------------------

class TestEmptyResults:
    def test_empty_returns_200_with_no_products(self, empty_client):
        body = empty_client.post("/api/products/similar", json={"productName": "XYZ"}).json()
        assert body["products"] == []

    def test_empty_data_source(self, empty_client):
        body = empty_client.post("/api/products/similar", json={"productName": "XYZ"}).json()
        assert body["dataSource"] == "empty"

    def test_empty_has_disclaimer(self, empty_client):
        body = empty_client.post("/api/products/similar", json={"productName": "XYZ"}).json()
        assert body["disclaimer"]


# ---------------------------------------------------------------------------
# Duplicate deduplication
# ---------------------------------------------------------------------------

class TestDeduplication:
    def test_duplicate_names_are_deduplicated(self):
        store = InMemoryStore()
        connector = _DuplicateSearchConnector()
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_connector] = lambda: connector
        with TestClient(app) as c:
            body = c.post("/api/products/similar", json={"productName": "Speaker"}).json()
        app.dependency_overrides.clear()
        names = [p["name"] for p in body["products"]]
        assert len(names) == len(set(names)), "Duplicate product names should be removed"


# ---------------------------------------------------------------------------
# Malformed / incomplete source data
# ---------------------------------------------------------------------------

class TestMalformedData:
    def test_malformed_results_do_not_crash(self):
        store = InMemoryStore()
        connector = _MalformedSearchConnector()
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_connector] = lambda: connector
        with TestClient(app) as c:
            resp = c.post("/api/products/similar", json={"productName": "Speaker"})
        app.dependency_overrides.clear()
        assert resp.status_code == 200
        # All malformed items (None, {}, blank name, "string") should be skipped
        assert resp.json()["products"] == []


# ---------------------------------------------------------------------------
# In-memory caching
# ---------------------------------------------------------------------------

class TestCaching:
    def test_second_call_returns_cache_data_source(self):
        store = InMemoryStore()
        connector = _LiveSearchConnector()
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_connector] = lambda: connector
        with TestClient(app) as c:
            c.post("/api/products/similar", json={"productName": "Speaker"})
            body2 = c.post("/api/products/similar", json={"productName": "Speaker"}).json()
        app.dependency_overrides.clear()
        assert body2["dataSource"] == "cache"

    def test_different_product_names_use_different_cache_keys(self):
        store = InMemoryStore()
        connector = _LiveSearchConnector()
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_connector] = lambda: connector
        with TestClient(app) as c:
            b1 = c.post("/api/products/similar", json={"productName": "Speaker"}).json()
            b2 = c.post("/api/products/similar", json={"productName": "Motor"}).json()
        app.dependency_overrides.clear()
        # First call is live, second call for a different product is also live (different key)
        assert b2["dataSource"] in ("live", "empty", "fixture")

    def test_cache_returns_same_products(self):
        store = InMemoryStore()
        connector = _LiveSearchConnector()
        app.dependency_overrides[get_store] = lambda: store
        app.dependency_overrides[get_connector] = lambda: connector
        with TestClient(app) as c:
            b1 = c.post("/api/products/similar", json={"productName": "Speaker"}).json()
            b2 = c.post("/api/products/similar", json={"productName": "Speaker"}).json()
        app.dependency_overrides.clear()
        assert [p["name"] for p in b1["products"]] == [p["name"] for p in b2["products"]]


# ---------------------------------------------------------------------------
# Secrets stay server-side
# ---------------------------------------------------------------------------

class TestSecrets:
    def test_response_does_not_contain_api_key(self, live_client):
        body = live_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        body_str = str(body)
        assert "TINYFISH_API_KEY" not in body_str
        assert "SECRET_KEY" not in body_str
        assert "DATABASE_URL" not in body_str

    def test_response_does_not_contain_backend_env_vars(self, fixture_client):
        body = fixture_client.post("/api/products/similar", json={"productName": "Speaker"}).json()
        body_str = str(body)
        for secret in ("TINYFISH_API_KEY", "SECRET_KEY", "DATABASE_URL", "CORS_ORIGINS"):
            assert secret not in body_str
