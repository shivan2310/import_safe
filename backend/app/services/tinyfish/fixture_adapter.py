"""Fixture TinyFish connector for the demo.

Returns canned results for the two demo listing URLs and the demo BIS registration number. Everything it returns is
marked ``is_fixture=True`` and every excerpt starts with ``[FIXTURE DATA]``, so it can never pass for real evidence.
Unknown URLs and registration numbers fall back to the live connector.
"""
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from app.decision.verification_normalizers import normalize_registration
from app.services.extraction.demo import DEMO_RAW_RESULT, DEMO_SOURCE_URL
from app.services.tinyfish.connector import TinyFishConnector
from app.services.tinyfish.live_adapter import LiveTinyFishConnector
from app.services.tinyfish.models import ExtractionResult, RegistryResult, delimit_untrusted

FIXTURE_PREFIX = "[FIXTURE DATA] "

# Second demo listing: the BT-100 speaker used by the 100-speaker report demo (tests/fixtures/demo_report_inputs.py).
BT100_SOURCE_URL = "https://seller.example/listing/bt-100"
BT100_LISTING_TEXT = "Portable Bluetooth Speaker BT-100, 10W, built-in 2000mAh battery. BIS R-41234567."

DEMO_REGISTRATION_NO = "R-41234567"
DEMO_REGISTRY_URL = "https://registry.example/crs/R41234567"
DEMO_REGISTRY_TEXT = (
    "Registration R-41234567, Shenzhen Example Audio Co, model BT-100, valid 2024-01-01 to 2027-01-01, status Active."
)


def _fx(text: str) -> str:
    return FIXTURE_PREFIX + text


def _listing_demo() -> Dict[str, Any]:
    raw = DEMO_RAW_RESULT
    specs = raw["specifications"]
    spec_text = "; ".join(f"{k}: {v}" for k, v in specs.items())
    fields = {
        "title": raw["title"], "price": raw["price"], "currency": raw["currency"], "moq": raw["moq"],
        "model": raw["model"], "specs": dict(specs), "certification_claims": list(raw["certification_claims"]),
    }
    excerpts = {
        "title": _fx(raw["title"]), "price": _fx(raw["price"]), "moq": _fx(raw["moq"]),
        "model": _fx("Model Number: " + raw["model"]), "specs": _fx(spec_text),
        "certification_claims": _fx("Certifications: " + ", ".join(raw["certification_claims"])),
    }
    return {"url": DEMO_SOURCE_URL, "fields": fields, "excerpts": excerpts, "text": raw["description"]}


def _bt100_demo() -> Dict[str, Any]:
    fields = {
        "title": "Portable Bluetooth Speaker BT-100", "model": "BT-100", "manufacturer": "Shenzhen Example Audio Co",
        "price": "10", "currency": "USD",
        "specs": {"Bluetooth Version": "5.0", "Battery Capacity": "2000mAh"},
        "certification_numbers": [DEMO_REGISTRATION_NO],
    }
    # Only fields that the listing text actually shows get an excerpt.
    excerpts = {
        "title": _fx(BT100_LISTING_TEXT), "model": _fx(BT100_LISTING_TEXT),
        "specs": _fx(BT100_LISTING_TEXT), "certification_numbers": _fx(BT100_LISTING_TEXT),
    }
    return {"url": BT100_SOURCE_URL, "fields": fields, "excerpts": excerpts, "text": BT100_LISTING_TEXT}


def _registry_demo() -> Dict[str, Any]:
    fields = {
        "registration_number": DEMO_REGISTRATION_NO, "manufacturer": "Shenzhen Example Audio Co",
        "model_scope": "BT-100", "valid_from": "2024-01-01", "valid_to": "2027-01-01", "status": "Active",
    }
    excerpts = {key: _fx(DEMO_REGISTRY_TEXT) for key in fields}
    return {"url": DEMO_REGISTRY_URL, "fields": fields, "excerpts": excerpts, "text": DEMO_REGISTRY_TEXT}


class FixtureTinyFishConnector:
    def __init__(
        self,
        live: Optional[TinyFishConnector] = None,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ):
        self._live = live
        self._now = now
        self._listings = {
            DEMO_SOURCE_URL: _listing_demo(),
            BT100_SOURCE_URL: _bt100_demo(),
        }
        self._registry = {normalize_registration(DEMO_REGISTRATION_NO): _registry_demo()}

    def _live_connector(self) -> TinyFishConnector:
        if self._live is None:
            self._live = LiveTinyFishConnector()
        return self._live

    def _common(self, canned: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "raw_text": delimit_untrusted(canned["text"]),
            "fields": dict(canned["fields"]),
            "source_url": canned["url"],
            "retrieved_at": self._now(),
            "excerpt_map": dict(canned["excerpts"]),
            "run_id": "fixture-run",
            "steps_used": 0,
            "status": "COMPLETED",
            "failed": False,
            "is_fixture": True,
        }

    async def extract_listing(self, url: str) -> ExtractionResult:
        canned = self._listings.get(url.strip()) if isinstance(url, str) else None
        if canned is None:
            return await self._live_connector().extract_listing(url)
        return ExtractionResult(**self._common(canned))

    async def fetch_registry_record(self, registration_no: str, manufacturer: str, model: str) -> RegistryResult:
        key = normalize_registration(registration_no) if isinstance(registration_no, str) else None
        canned = self._registry.get(key) if key else None
        if canned is None:
            return await self._live_connector().fetch_registry_record(registration_no, manufacturer, model)
        return RegistryResult(record_found=True, **self._common(canned))
