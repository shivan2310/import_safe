import httpx
import pytest
from fastapi.testclient import TestClient

from app.errors import (
    IncompleteExtractionError,
    InvalidUrlError,
    PageUnavailableError,
    TinyFishFailureError,
)
from app.main import app
from app.services.extraction import extract_raw_product
from app.services.normalization import normalize_product
from app.services.tinyfish import TinyFishClient

URL = "https://www.alibaba.com/product-detail/x_1.html"


def client_returning(body: dict, status: int = 200) -> TinyFishClient:
    transport = httpx.MockTransport(lambda req: httpx.Response(status, json=body))
    return TinyFishClient(api_key="k", transport=transport)


def test_live_extraction_and_normalization_keep_unknowns_null():
    body = {"run_id": "r1", "status": "COMPLETED",
            "result": {"title": "Earbuds", "price": "US$1,200.50-2,000", "moq": "50 pieces",
                       "wifi": None, "certification_claims": ["CE"]}}
    raw = extract_raw_product(URL, client_returning(body))
    assert raw.retrieval_mode == "live" and raw.run_id == "r1"
    product, missing = normalize_product(raw.raw_result, URL)
    assert product.price == 1200.5 and product.price_max == 2000.0
    assert product.currency == "USD" and product.moq == 50
    assert product.voltage is None and "voltage" in missing
    assert product.source_url == URL


def test_ambiguous_dollar_sign_leaves_currency_unknown():
    product, _ = normalize_product({"title": "A", "price": "$5"}, URL)
    assert product.currency is None


def test_errors():
    with pytest.raises(InvalidUrlError):
        extract_raw_product("not a url", client_returning({}))
    with pytest.raises(InvalidUrlError):
        extract_raw_product("http://localhost/x", client_returning({}))
    with pytest.raises(TinyFishFailureError):
        extract_raw_product(URL, client_returning({}, status=500))
    with pytest.raises(TinyFishFailureError):
        extract_raw_product(URL, client_returning({"status": "FAILED", "error": {"message": "boom"}}))
    with pytest.raises(PageUnavailableError):
        extract_raw_product(URL, client_returning(
            {"status": "COMPLETED", "result": {"status": "failure", "reason": "blocked"}}))
    with pytest.raises(IncompleteExtractionError):
        normalize_product({"seller": "only seller"}, URL)


def test_api_demo_mode_is_labelled():
    r = TestClient(app).post("/api/v1/analyze", json={"url": URL, "mode": "demo"})
    body = r.json()
    assert r.status_code == 200
    assert body["retrieval_mode"] == "demo" and body["mode"] == "DEMO"
    assert body["raw"]["provider"] == "demo_fixture"
    assert body["product"]["certification_claims_basis"] == "SELLER_CLAIM"


def test_api_fallback_and_errors(monkeypatch):
    monkeypatch.delenv("TINYFISH_API_KEY", raising=False)
    c = TestClient(app)
    r = c.post("/api/v1/analyze", json={"url": URL})
    assert r.json()["retrieval_mode"] == "demo"
    assert "tinyfish_not_configured" in r.json()["fallback_reason"]

    monkeypatch.setenv("ALLOW_DEMO_FALLBACK", "false")
    r = c.post("/api/v1/analyze", json={"url": URL})
    assert r.status_code == 503 and r.json()["detail"]["code"] == "tinyfish_not_configured"

    r = c.post("/api/v1/analyze", json={"url": "nope"})
    assert r.status_code == 422 and r.json()["detail"]["code"] == "invalid_url"
