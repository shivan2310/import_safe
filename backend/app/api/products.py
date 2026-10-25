"""Similar-products endpoint: POST /api/products/similar.

Retrieves up to 5 functionally similar products from public marketplace search results
via the TinyFish connector. Results are cached for 24 h.

Verification model — honest:
  There is no authoritative seller-verification database in this system. All results
  carry verificationStatus = "marketplace_listed" (found on a public marketplace) or
  "fixture" (demo data). A verified badge is never shown.

Demo fallback (ALLOW_DEMO_FALLBACK):
  When the connector is a FixtureTinyFishConnector (or TinyFish is not configured),
  fixture products are returned with isFixture=True. Fixture data is never presented
  as genuine supplier discovery.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.api.investigations import get_connector, get_store
from app.coordinator.store import InMemoryStore
from app import config
from app.services.tinyfish.models import clean_text

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/products", tags=["products"])

CACHE_TTL_HOURS = 24
DISCLAIMER = (
    "Product listings are retrieved from public marketplaces. "
    "Seller identity and product quality are not independently verified. "
    "Prices are supplier-quoted and subject to change."
)

# ---------------------------------------------------------------------------
# In-memory cache used when no Postgres pool is available (InMemoryStore path)
# ---------------------------------------------------------------------------
_mem_cache: Dict[str, Any] = {}


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------

class SimilarProductsRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    productName: str = Field(min_length=1, max_length=200)
    specs: Optional[Dict[str, Any]] = None
    investigationId: Optional[str] = None


class SellerInfo(BaseModel):
    name: str
    verificationStatus: str  # "marketplace_listed" | "fixture" | "unverified"


class SimilarProduct(BaseModel):
    id: str
    name: str
    seller: SellerInfo
    price: Optional[str] = None
    currency: Optional[str] = None
    moq: Optional[str] = None
    origin: Optional[str] = None
    sourceUrl: Optional[str] = None
    matchReasons: List[str]
    isFixture: bool


class SimilarProductsResponse(BaseModel):
    products: List[SimilarProduct]
    dataSource: str  # "live" | "fixture" | "cache" | "empty"
    isFixture: bool
    disclaimer: str


# ---------------------------------------------------------------------------
# Cache helpers
# ---------------------------------------------------------------------------

def _cache_key(product_name: str, specs: Optional[Dict]) -> str:
    name = clean_text(product_name, 200).lower().strip()
    specs_str = json.dumps(specs or {}, sort_keys=True, default=str)
    return hashlib.sha256(f"{name}|{specs_str}".encode()).hexdigest()[:32]


def _mem_cache_get(key: str) -> Optional[Dict]:
    entry = _mem_cache.get(key)
    if not entry:
        return None
    if datetime.now(timezone.utc) > entry["expires_at"]:
        _mem_cache.pop(key, None)
        return None
    return entry


def _mem_cache_put(key: str, product_name: str, results: Dict) -> None:
    _mem_cache[key] = {
        "results": results,
        "expires_at": datetime.now(timezone.utc) + timedelta(hours=CACHE_TTL_HOURS),
    }


async def _db_cache_get(pool, key: str) -> Optional[Dict]:
    try:
        row = await pool.fetchrow(
            "SELECT results FROM similar_products_cache WHERE cache_key = $1 AND expires_at > $2",
            key, datetime.now(timezone.utc),
        )
        if row:
            return row["results"]
    except Exception:
        log.warning("similar_products_cache read failed")
    return None


async def _db_cache_put(pool, key: str, product_name: str, results: Dict) -> None:
    now = datetime.now(timezone.utc)
    try:
        await pool.execute(
            "INSERT INTO similar_products_cache (cache_key, product_name, results, retrieved_at, expires_at) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (cache_key) DO UPDATE SET results=$3, retrieved_at=$4, expires_at=$5",
            key, clean_text(product_name, 200), json.dumps(results),
            now, now + timedelta(hours=CACHE_TTL_HOURS),
        )
    except Exception:
        log.warning("similar_products_cache write failed")


# ---------------------------------------------------------------------------
# Result normalisation
# ---------------------------------------------------------------------------

def _match_reasons(product_name: str, result_name: str) -> List[str]:
    reasons = ["Retrieved from Alibaba search results"]
    name_lower = product_name.lower()
    res_lower = result_name.lower()
    # Simple word overlap heuristic — never fabricated
    shared = set(name_lower.split()) & set(res_lower.split())
    shared.discard("the"); shared.discard("a"); shared.discard("an")
    if shared:
        reasons.append(f"Shares keyword(s): {', '.join(sorted(shared)[:3])}")
    return reasons


def _normalize_products(
    raw: List[Dict],
    product_name: str,
    is_fixture: bool,
) -> List[SimilarProduct]:
    out: List[SimilarProduct] = []
    seen_names: set = set()
    for i, item in enumerate(raw[:5]):
        if not isinstance(item, dict):
            continue
        name = clean_text(str(item.get("name") or item.get("title") or ""), 200)
        if not name or name in seen_names:
            continue
        seen_names.add(name)
        verification = "fixture" if is_fixture else "marketplace_listed"
        seller_name = clean_text(str(item.get("seller") or "Unknown seller"), 200)
        out.append(SimilarProduct(
            id=f"sp-{i}-{hashlib.md5(name.encode()).hexdigest()[:8]}",
            name=name,
            seller=SellerInfo(name=seller_name, verificationStatus=verification),
            price=clean_text(str(item["price"]), 100) if item.get("price") else None,
            currency=clean_text(str(item["currency"]), 20) if item.get("currency") else None,
            moq=clean_text(str(item["moq"]), 100) if item.get("moq") else None,
            origin=clean_text(str(item["origin"]), 100) if item.get("origin") else None,
            sourceUrl=clean_text(str(item.get("sourceUrl") or item.get("url") or ""), 500) or None,
            matchReasons=_match_reasons(product_name, name),
            isFixture=is_fixture,
        ))
    return out


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.post("/similar", response_model=SimilarProductsResponse)
async def similar_products(
    req: SimilarProductsRequest,
    store=Depends(get_store),
    connector=Depends(get_connector),
):
    product_name = req.productName.strip()
    if not product_name:
        raise HTTPException(status_code=422, detail="productName must not be blank")

    key = _cache_key(product_name, req.specs)

    # --- Try cache first ---
    pool = None if isinstance(store, InMemoryStore) else getattr(store, "_pool", None)
    cached = None
    if pool:
        cached = await _db_cache_get(pool, key)
    else:
        entry = _mem_cache_get(key)
        if entry:
            cached = entry["results"]

    if cached:
        resp = SimilarProductsResponse(**cached)
        resp = SimilarProductsResponse(
            products=resp.products,
            dataSource="cache",
            isFixture=resp.isFixture,
            disclaimer=DISCLAIMER,
        )
        return resp

    # --- Live search ---
    search_fn = getattr(connector, "search_products", None)
    if search_fn is None:
        # Connector does not support search — return empty
        result = SimilarProductsResponse(
            products=[], dataSource="empty", isFixture=False, disclaimer=DISCLAIMER,
        )
        return result

    try:
        raw_products, data_source = await search_fn(product_name, req.specs)
    except Exception:
        log.exception("search_products failed for %r", product_name)
        raw_products, data_source = [], "empty"

    is_fixture = (data_source == "fixture")

    # Fixture data check: demo data must never appear as genuine discovery
    if is_fixture and not config.allow_demo_fallback():
        result = SimilarProductsResponse(
            products=[], dataSource="empty", isFixture=False, disclaimer=DISCLAIMER,
        )
        return result

    products = _normalize_products(raw_products, product_name, is_fixture)

    result = SimilarProductsResponse(
        products=products,
        dataSource=data_source,
        isFixture=is_fixture,
        disclaimer=DISCLAIMER,
    )

    # --- Cache the result ---
    payload = result.model_dump()
    if pool:
        await _db_cache_put(pool, key, product_name, payload)
    else:
        _mem_cache_put(key, product_name, payload)

    return result
