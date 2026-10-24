"""The TinyFish connector interface (docs/prd-backend.md B1 and B6).

Implementations never raise on a TinyFish failure: they return a result with ``failed=True``.
"""
from typing import Protocol, runtime_checkable

from app.services.tinyfish.models import ExtractionResult, RegistryResult


@runtime_checkable
class TinyFishConnector(Protocol):
    async def extract_listing(self, url: str) -> ExtractionResult:
        """Task A: extract the product listing at ``url``."""
        ...

    async def fetch_registry_record(self, registration_no: str, manufacturer: str, model: str) -> RegistryResult:
        """Task B: look up an official registration record."""
        ...
