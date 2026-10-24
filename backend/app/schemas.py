from typing import Any

from pydantic import BaseModel


class AnalyzeRequest(BaseModel):
    url: str
    mode: str = "live"  # "live" | "demo" (demo = labelled sample data, no retrieval)


class Product(BaseModel):
    title: str | None = None
    seller: str | None = None
    price: float | None = None
    price_max: float | None = None
    currency: str | None = None
    moq: int | None = None
    description: str | None = None
    specifications: dict[str, str] | None = None
    model: str | None = None
    material: str | None = None
    voltage: str | None = None
    bluetooth: str | None = None
    wifi: str | None = None
    battery: str | None = None
    battery_type: str | None = None
    # Seller claims only — NOT independently verified.
    certification_claims: list[str] | None = None
    certification_claims_basis: str = "SELLER_CLAIM"
    image: str | None = None
    source_url: str


class AnalyzeResponse(BaseModel):
    mode: str  # upper-case retrieval mode, kept for the existing frontend badge
    retrieval_mode: str  # "live" | "demo"
    product: Product
    missing_fields: list[str] = []
    fallback_reason: str | None = None
    raw: dict[str, Any]
