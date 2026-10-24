from fastapi import APIRouter

from app import config
from app.errors import ImportSafeError
from app.schemas import AnalyzeRequest, AnalyzeResponse
from app.services.extraction import demo_raw_product, extract_raw_product
from app.services.extraction.urls import validate_product_url
from app.services.normalization import normalize_product

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/api/v1/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest) -> AnalyzeResponse:
    url = validate_product_url(req.url)  # invalid URLs never fall back to demo

    if req.mode == "demo":
        raw = demo_raw_product(url, "demo mode requested")
    else:
        try:
            raw = extract_raw_product(url)
            product, missing = normalize_product(raw.raw_result, url)
        except ImportSafeError as exc:
            if not config.allow_demo_fallback():
                raise
            raw = demo_raw_product(url, f"{exc.code}: {exc.message}")

    if raw.retrieval_mode == "demo":
        # Demo product keeps its own sample source URL; the requested URL lives in raw.
        product, missing = normalize_product(raw.raw_result, url)

    return AnalyzeResponse(
        mode=raw.retrieval_mode.upper(),
        retrieval_mode=raw.retrieval_mode,
        product=product,
        missing_fields=missing,
        fallback_reason=raw.fallback_reason,
        raw=raw.model_dump(),
    )
