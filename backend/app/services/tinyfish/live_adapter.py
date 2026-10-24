"""Live TinyFish connector: start a run with run-async, then poll GET /v1/runs/{run_id}.

Endpoints and run fields were checked against docs.tinyfish.ai (decisions.md section 11). The connector never
raises on a TinyFish problem: a missing key, HTTP error, bad response, timeout or non-COMPLETED run gives a
result with ``failed=True``. Page text is cleaned and delimited, and is never logged.
"""
import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Sequence

import httpx

from app import config
from app.services.tinyfish.goals import (
    DEFAULT_REGISTRY_URL, LISTING_GOAL, LISTING_KEYS, REGISTRY_KEYS, registry_goal,
)
from app.services.tinyfish.models import (
    ExtractionResult, RegistryResult, clean_text, extract_fields, raw_text_from_result,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 3.0
TIMEOUT_S = 90.0
REQUEST_TIMEOUT_S = 15.0
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}


class LiveTinyFishConnector:
    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        registry_url: str = DEFAULT_REGISTRY_URL,
        poll_interval_s: float = POLL_INTERVAL_S,
        timeout_s: float = TIMEOUT_S,
        transport: Optional[httpx.AsyncBaseTransport] = None,
        sleep: Callable[[float], Any] = asyncio.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.api_key = api_key if api_key is not None else config.tinyfish_api_key()
        self.base_url = (base_url or config.tinyfish_base_url()).rstrip("/")
        self.registry_url = registry_url
        self.poll_interval_s = poll_interval_s
        self.timeout_s = timeout_s
        self._transport = transport
        self._sleep = sleep
        self._clock = clock

    async def extract_listing(self, url: str) -> ExtractionResult:
        outcome = await self._run(url, LISTING_GOAL, LISTING_KEYS)
        # A listing with nothing extracted is unusable, so it counts as failed.
        failed = outcome["failed"] or not outcome["fields"]
        return ExtractionResult(failed=failed, **{k: v for k, v in outcome.items() if k != "failed"})

    async def fetch_registry_record(self, registration_no: str, manufacturer: str, model: str) -> RegistryResult:
        outcome = await self._run(self.registry_url, registry_goal(registration_no, manufacturer, model), REGISTRY_KEYS)
        record_found = not outcome["failed"] and "registration_number" in outcome["fields"]
        return RegistryResult(record_found=record_found, **outcome)

    async def _run(self, url: str, goal: str, allowed_keys: Sequence[str]) -> Dict[str, Any]:
        """Run one task and return the keyword arguments for a result. Never raises."""
        source_url = clean_text(url, 2000) or "N/A"
        run_id: Optional[str] = None
        try:
            if not self.api_key:
                return self._failure(source_url, run_id, "NOT_CONFIGURED")
            if not source_url.lower().startswith(("http://", "https://")):
                return self._failure(source_url, run_id, "INVALID_URL")
            headers = {"X-API-Key": self.api_key}
            deadline = self._clock() + self.timeout_s
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_S, transport=self._transport) as http:
                start = await http.post(
                    f"{self.base_url}/v1/automation/run-async", headers=headers, json={"url": source_url, "goal": goal},
                )
                if start.status_code >= 400:
                    return self._failure(source_url, run_id, f"HTTP_{start.status_code}")
                started = start.json()
                run_id = clean_text(started.get("run_id"), 200) if isinstance(started, dict) else ""
                if not run_id:
                    return self._failure(source_url, None, "NO_RUN_ID")
                while True:
                    poll = await http.get(f"{self.base_url}/v1/runs/{run_id}", headers=headers)
                    if poll.status_code >= 400:
                        return self._failure(source_url, run_id, f"HTTP_{poll.status_code}")
                    run = poll.json()
                    status = str(run.get("status", "")).upper() if isinstance(run, dict) else ""
                    if status in TERMINAL_STATUSES:
                        return self._finish(source_url, run_id, status, run, allowed_keys)
                    remaining = deadline - self._clock()
                    if remaining <= 0:
                        # The remote run is not cancelled; it expires on TinyFish's side (section 11).
                        logger.warning("tinyfish run %s timed out after %ss", run_id, self.timeout_s)
                        return self._failure(source_url, run_id, "TIMEOUT")
                    await self._sleep(min(self.poll_interval_s, remaining))
        except Exception as exc:  # never raise: a connector failure is a failed result
            logger.warning("tinyfish run %s failed: %s", run_id, type(exc).__name__)
            return self._failure(source_url, run_id, "ERROR")

    def _finish(self, source_url: str, run_id: str, status: str, run: Dict[str, Any],
                allowed_keys: Sequence[str]) -> Dict[str, Any]:
        result = run.get("result")
        page_blocked = isinstance(result, dict) and str(result.get("status", "")).lower() == "failure"
        fields, excerpts = ({}, {}) if page_blocked else extract_fields(result, allowed_keys)
        steps = run.get("num_of_steps")
        failed = status != "COMPLETED" or page_blocked
        logger.info("tinyfish run %s finished: status=%s fields=%d", run_id, status, len(fields))
        return {
            "raw_text": raw_text_from_result(result) if result is not None else "",
            "fields": fields,
            "source_url": source_url,
            "retrieved_at": datetime.now(timezone.utc),
            "excerpt_map": excerpts,
            "run_id": run_id,
            "steps_used": steps if isinstance(steps, int) and not isinstance(steps, bool) else 0,
            "status": status if not page_blocked else "PAGE_UNAVAILABLE",
            "failed": failed,
        }

    @staticmethod
    def _failure(source_url: str, run_id: Optional[str], status: str) -> Dict[str, Any]:
        return {
            "raw_text": "",
            "fields": {},
            "source_url": source_url,
            "retrieved_at": datetime.now(timezone.utc),
            "excerpt_map": {},
            "run_id": run_id,
            "steps_used": 0,
            "status": status,
            "failed": True,
        }
