import re
from typing import Any

from app.errors import IncompleteExtractionError
from app.schemas import Product

# Reported as missing when null ('image' and 'wifi' are often legitimately absent).
_TRACKED = [
    "title", "seller", "price", "currency", "moq", "description", "specifications",
    "model", "material", "voltage", "bluetooth", "wifi", "battery", "battery_type",
    "certification_claims", "image",
]
_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")
_CURRENCY = [("US$", "USD"), ("USD", "USD"), ("CNY", "CNY"), ("RMB", "CNY"),
             ("INR", "INR"), ("EUR", "EUR"), ("GBP", "GBP")]


def _text(v: Any) -> str | None:
    if v is None or isinstance(v, (dict, list)):
        return None
    s = str(v).strip()
    return s if s and s.lower() not in ("null", "none", "n/a", "unknown") else None


def _numbers(v: Any) -> list[float]:
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return [float(v)]
    s = _text(v)
    return [float(m.replace(",", "")) for m in _NUM.findall(s)] if s else []


def _currency(raw_currency: Any, raw_price: Any) -> str | None:
    for source in (_text(raw_currency), _text(raw_price)):
        if source:
            up = source.upper()
            for token, code in _CURRENCY:
                if token.upper() in up:
                    return code
    return None  # a bare "$" is ambiguous; stay unknown


def _specs(v: Any) -> dict[str, str] | None:
    if not isinstance(v, dict):
        return None
    out = {str(k): s for k, val in v.items() if (s := _text(val)) is not None}
    return out or None


def _claims(v: Any) -> list[str] | None:
    items = v if isinstance(v, list) else [v]
    out = [s for i in items if (s := _text(i))]
    return out or None


def normalize_product(raw: Any, requested_url: str) -> tuple[Product, list[str]]:
    """Map raw TinyFish output to a Product. Returns (product, missing_fields)."""
    if isinstance(raw, dict) and isinstance(raw.get("product"), dict):
        raw = raw["product"]
    if isinstance(raw, dict) and isinstance(raw.get("result"), dict):
        raw = raw["result"]
    if not isinstance(raw, dict):
        raise IncompleteExtractionError("Extraction result was not a product object")

    prices = _numbers(raw.get("price"))
    moq_nums = _numbers(raw.get("moq"))
    product = Product(
        title=_text(raw.get("title")),
        seller=_text(raw.get("seller")),
        price=min(prices) if prices else None,
        price_max=max(prices) if len(prices) > 1 else None,
        currency=_currency(raw.get("currency"), raw.get("price")),
        moq=int(moq_nums[0]) if moq_nums else None,
        description=_text(raw.get("description")),
        specifications=_specs(raw.get("specifications")),
        model=_text(raw.get("model")),
        material=_text(raw.get("material")),
        voltage=_text(raw.get("voltage")),
        bluetooth=_text(raw.get("bluetooth")),
        wifi=_text(raw.get("wifi")),
        battery=_text(raw.get("battery")),
        battery_type=_text(raw.get("battery_type")),
        certification_claims=_claims(raw.get("certification_claims")),
        image=_text(raw.get("image")),
        source_url=_text(raw.get("source_url")) or requested_url,
    )
    if product.title is None and product.price is None:
        raise IncompleteExtractionError(
            "Extraction returned neither a title nor a price; page may not be a product page"
        )
    missing = [f for f in _TRACKED if getattr(product, f) is None]
    return product, missing
