from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.errors import PageUnavailableError, TinyFishFailureError
from app.services.tinyfish import TinyFishClient

from .demo import DEMO_RAW_RESULT
from .goal import PRODUCT_GOAL
from .urls import validate_product_url


class RawEvidence(BaseModel):
    """Unmodified retrieval output, kept separate from the normalized product."""

    requested_url: str
    retrieval_mode: str  # "live" | "demo"
    provider: str  # "tinyfish" | "demo_fixture"
    run_id: str | None = None
    status: str | None = None
    retrieved_at: str
    raw_result: Any = None
    fallback_reason: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def extract_raw_product(url: str, client: TinyFishClient | None = None) -> RawEvidence:
    url = validate_product_url(url)
    run = (client or TinyFishClient()).run(url, PRODUCT_GOAL)

    result = run.result
    if result is None:
        raise TinyFishFailureError("TinyFish completed without a result")
    if isinstance(result, dict) and str(result.get("status", "")).lower() == "failure":
        raise PageUnavailableError(result.get("reason") or "Page could not be read")
    return RawEvidence(
        requested_url=url,
        retrieval_mode="live",
        provider="tinyfish",
        run_id=run.run_id,
        status=run.status,
        retrieved_at=_now(),
        raw_result=result,
    )


def demo_raw_product(url: str, reason: str | None = None) -> RawEvidence:
    return RawEvidence(
        requested_url=url,
        retrieval_mode="demo",
        provider="demo_fixture",
        retrieved_at=_now(),
        raw_result=DEMO_RAW_RESULT,
        fallback_reason=reason,
    )
