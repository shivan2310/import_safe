"""Thin TinyFish Agent API client (synchronous run endpoint).

Docs: https://docs.tinyfish.ai — POST /v1/automation/run, auth via X-API-Key.
"""
from dataclasses import dataclass
from typing import Any

import httpx

from app import config
from app.errors import TinyFishFailureError, TinyFishNotConfiguredError


@dataclass
class TinyFishRun:
    run_id: str | None
    status: str
    result: Any
    error: dict | None


class TinyFishClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float | None = None,
        transport: httpx.BaseTransport | None = None,
    ):
        self.api_key = api_key or config.tinyfish_api_key()
        self.base_url = (base_url or config.tinyfish_base_url()).rstrip("/")
        self.timeout_s = timeout_s or config.tinyfish_timeout_s()
        self._transport = transport

    def run(self, url: str, goal: str) -> TinyFishRun:
        if not self.api_key:
            raise TinyFishNotConfiguredError("TINYFISH_API_KEY is not set")
        try:
            with httpx.Client(timeout=self.timeout_s, transport=self._transport) as http:
                resp = http.post(
                    f"{self.base_url}/v1/automation/run",
                    headers={"X-API-Key": self.api_key},
                    json={"url": url, "goal": goal},
                )
        except httpx.HTTPError as exc:
            raise TinyFishFailureError(f"TinyFish request failed: {exc}") from exc

        if resp.status_code >= 400:
            raise TinyFishFailureError(f"TinyFish returned HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise TinyFishFailureError("TinyFish returned a non-JSON response") from exc

        run = TinyFishRun(
            run_id=body.get("run_id"),
            status=str(body.get("status", "UNKNOWN")),
            result=body.get("result"),
            error=body.get("error"),
        )
        if run.status != "COMPLETED":
            msg = (run.error or {}).get("message") or f"run ended with status {run.status}"
            raise TinyFishFailureError(f"TinyFish run not completed: {msg}")
        return run
