"""Live TinyFish connector: fetch page content via the TinyFish Fetch API, parse fields
directly from the returned markdown, and fall back to run-async automation when fetch fails.

Design (docs/prd-backend.md B6):
- Listing extraction: POST https://api.fetch.tinyfish.ai/ -> markdown text -> regex parse.
  Fetch renders JS and is free; automation ($0.016/step) is only used when fetch fails.
- Registry lookup and similar-product search: run-async automation (genuine browser interaction needed).
- Never raises: any connector failure returns a result with ``failed=True``.
- Page text is untrusted data and is never logged.
"""
import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

import httpx

from app import config
from app.services.tinyfish.goals import (
    DEFAULT_REGISTRY_URL, LISTING_GOAL, LISTING_KEYS, REGISTRY_KEYS, SIMILAR_SEARCH_KEYS,
    ALIBABA_SEARCH_URL, registry_goal, similar_search_goal,
)
from app.services.tinyfish.models import (
    ExtractionResult, RegistryResult, clean_text, delimit_untrusted, extract_fields, raw_text_from_result,
)

logger = logging.getLogger(__name__)

POLL_INTERVAL_S = 3.0
TIMEOUT_S = 90.0
REQUEST_TIMEOUT_S = 15.0
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "CANCELLED"}

FETCH_BASE_URL = "https://api.fetch.tinyfish.ai"
SEARCH_BASE_URL = "https://api.search.tinyfish.ai"
FETCH_TIMEOUT_S = 30.0


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
        # Preferred path: TinyFish fetch (free, renders JS) then Ollama extraction.
        fetch_result = await self._extract_via_fetch(url)
        if fetch_result is not None:
            return fetch_result
        # Fallback: browser automation.
        outcome = await self._run(url, LISTING_GOAL, LISTING_KEYS)
        failed = outcome["failed"] or not outcome["fields"]
        return ExtractionResult(failed=failed, **{k: v for k, v in outcome.items() if k != "failed"})

    _GEO_BLOCK_PHRASES = ("can't be shipped to your region", "cannot be placed and/or shipped", "product not available")

    async def _extract_via_fetch(self, url: str) -> Optional[ExtractionResult]:
        """Fetch page via TinyFish Fetch API and parse fields from markdown. Returns None to fall back."""
        source_url = clean_text(url, 2000) or "N/A"
        page_text = await self._fetch_page_text(url)
        if page_text is None:
            return None
        # Detect Alibaba geo-block — return a clear failed result instead of falling through to automation
        lower = page_text.lower()
        if any(phrase in lower for phrase in self._GEO_BLOCK_PHRASES):
            logger.warning("alibaba geo-block detected for %s", source_url)
            return ExtractionResult(
                raw_text="",
                fields={},
                source_url=source_url,
                retrieved_at=datetime.now(timezone.utc),
                excerpt_map={},
                run_id=None,
                steps_used=0,
                status="GEO_BLOCKED",
                failed=True,
            )
        extracted_json = self._parse_markdown_fields(page_text)
        if extracted_json is None:
            return None
        fields, excerpts = extract_fields(extracted_json, LISTING_KEYS)
        if not fields:
            logger.warning("fetch+parse returned no fields for %s", source_url)
            return None
        logger.info("fetch+parse succeeded for %s: fields=%d", source_url, len(fields))
        return ExtractionResult(
            raw_text=delimit_untrusted(page_text),
            fields=fields,
            source_url=source_url,
            retrieved_at=datetime.now(timezone.utc),
            excerpt_map=excerpts,
            run_id=None,
            steps_used=0,
            status="COMPLETED",
            failed=False,
        )

    async def _fetch_page_text(self, url: str) -> Optional[str]:
        """Fetch page markdown via TinyFish Fetch API (free, renders JS). Returns None on any failure."""
        if not self.api_key:
            return None
        try:
            async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, transport=self._transport) as http:
                resp = await http.post(
                    FETCH_BASE_URL + "/",
                    headers={"X-API-Key": self.api_key},
                    json={
                        "urls": [url],
                        "format": "markdown",
                        "links": False,
                        "image_links": False,
                        "iframe_links": False,
                        "page_metadata": False,
                        "purpose": "Extract product listing fields for import compliance analysis",
                    },
                )
            if resp.status_code >= 400:
                logger.warning("tinyfish fetch HTTP %s for %s", resp.status_code, url)
                return None
            data = resp.json()
            results = data.get("results", [])
            if not results:
                errors = data.get("errors", [])
                code = errors[0].get("error", "unknown") if errors else "no_results"
                logger.warning("tinyfish fetch failed for %s: %s", url, code)
                return None
            text = results[0].get("text") or ""
            return text.strip() or None
        except Exception as exc:
            logger.warning("tinyfish fetch error for %s: %s", url, type(exc).__name__)
            return None

    @staticmethod
    def _parse_markdown_fields(text: str) -> Optional[Dict[str, Any]]:
        """Parse product fields directly from TinyFish markdown without an LLM.

        TinyFish fetch returns clean structured markdown. Key attributes appear as
        alternating label / value lines under the '### Key attributes' heading.
        """
        result: Dict[str, Any] = {}

        # Title: first H1
        title_m = re.search(r'^#\s+(.+)$', text, re.MULTILINE)
        if title_m:
            title_val = clean_text(title_m.group(1), 500)
            if title_val:
                result["title"] = {"value": title_val, "excerpt": title_m.group(0).strip()}

        # Price and currency
        price_m = re.search(r'(\$)([\d,]+(?:\.\d+)?(?:\s*[-–]\s*[\d,]+(?:\.\d+)?)?)', text)
        if price_m:
            result["price"] = {"value": price_m.group(0).strip(), "excerpt": price_m.group(0).strip()}
            result["currency"] = {"value": "USD", "excerpt": price_m.group(1)}

        # MOQ
        moq_m = re.search(r'[Mm]inimum order quantity[:\s]+([^\n]+)', text)
        if moq_m:
            result["moq"] = {"value": moq_m.group(1).strip(), "excerpt": moq_m.group(0).strip()}

        # Key attributes — label/value pairs separated by blank lines
        # Map of page label (lower) → LISTING_KEYS field name (None = goes into specs)
        _LABEL_MAP: Dict[str, Optional[str]] = {
            "place of origin": "origin",
            "brand": "manufacturer",
            "model number": "model",
            "interface": None,
            "keyboard standard": None,
            "dpi": None,
            "feature": None,
            "anti-ghosting": None,
            "keyboard backlit": None,
            "backlit": None,
            "mechanical": None,
            "supports human engineering": None,
            "wrist support": None,
            "type": None,
            "mouse connection": None,
        }
        attrs_m = re.search(
            r'(?:###?\s*Key attributes)(.*?)(?:###?|\Z)', text, re.DOTALL | re.IGNORECASE
        )
        specs: Dict[str, str] = {}
        if attrs_m:
            lines: List[str] = [
                ln.strip() for ln in attrs_m.group(1).split('\n') if ln.strip()
            ]
            i = 0
            while i < len(lines) - 1:
                label = lines[i].lower().strip()
                value = lines[i + 1].strip()
                # Skip markdown table separators and empty values
                if '|' in value or not value:
                    i += 1
                    continue
                if label in _LABEL_MAP:
                    mapped = _LABEL_MAP[label]
                    if mapped and mapped not in result:
                        result[mapped] = {"value": value, "excerpt": f"{lines[i]}\n{value}"}
                    elif mapped is None:
                        specs[lines[i]] = value
                    i += 2
                else:
                    i += 1
        if specs:
            result["specs"] = {"value": specs, "excerpt": "Key attributes section"}

        # Seller / manufacturer fallback from "Know your supplier"
        if "manufacturer" not in result:
            seller_m = re.search(r'(?:Know your supplier|Lingdong|Co\., Ltd\.)[^\n]*\n([^\n]+)', text)
            if seller_m:
                result["manufacturer"] = {"value": seller_m.group(1).strip(), "excerpt": seller_m.group(0).strip()}

        # Certification claims — known mark names found in the text
        _CERT_MARKS = ["CE", "FCC", "RoHS", "BIS", "WEEE", "UL", "KC", "EAC", "CCC"]
        found: List[str] = [c for c in _CERT_MARKS if re.search(r'\b' + c + r'\b', text)]
        if found:
            result["certification_claims"] = {"value": found, "excerpt": " ".join(found)}

        return result if result else None

    async def fetch_registry_record(self, registration_no: str, manufacturer: str, model: str) -> RegistryResult:
        outcome = await self._run(self.registry_url, registry_goal(registration_no, manufacturer, model), REGISTRY_KEYS)
        record_found = not outcome["failed"] and "registration_number" in outcome["fields"]
        return RegistryResult(record_found=record_found, **outcome)

    async def search_products(
        self, product_name: str, specs: "dict | None" = None
    ) -> "tuple[list[dict], str]":
        """Search Alibaba for similar products via TinyFish Search API (free). Never raises."""
        from app.services.tinyfish.goals import safe_search_term
        term = safe_search_term(product_name, 80)
        if not term:
            return [], "empty"

        products = await self._search_via_tinyfish(term)
        if products:
            logger.info("search returned %d products for %r", len(products), product_name)
            return products, "live"
        return [], "empty"

    async def _search_via_tinyfish(self, term: str) -> "list[dict]":
        """Call TinyFish Search API to find Alibaba product listings. Free, no automation credits."""
        if not self.api_key:
            return []
        query = f"site:alibaba.com {term}"
        try:
            async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_S, transport=self._transport) as http:
                resp = await http.get(
                    SEARCH_BASE_URL + "/",
                    headers={"X-API-Key": self.api_key},
                    params={"query": query, "include_domains": "alibaba.com"},
                )
            if resp.status_code >= 400:
                logger.warning("tinyfish search HTTP %s for %r", resp.status_code, term)
                return []
            data = resp.json()
            results = data.get("results", [])
        except Exception as exc:
            logger.warning("tinyfish search error: %s", type(exc).__name__)
            return []

        products: "list[dict]" = []
        for item in results:
            url = item.get("url", "")
            if "alibaba.com/product-detail/" not in url:
                continue
            title = (item.get("title") or "").strip()
            if not title:
                continue
            snippet = item.get("snippet") or ""
            entry: "dict" = {"name": title[:200], "sourceUrl": url[:500]}
            # Parse price from snippet: $X or $X-Y
            price_m = re.search(r'\$[\d,]+(?:\.\d+)?(?:\s*[-–]\s*[\d,]+(?:\.\d+)?)?', snippet)
            if price_m:
                entry["price"] = price_m.group(0).strip()
                entry["currency"] = "USD"
            # MOQ: "N pieces" pattern in snippet
            moq_m = re.search(r'(\d[\d,]*)\s*(?:pieces?|pcs?|units?|sets?)', snippet, re.IGNORECASE)
            if moq_m:
                entry["moq"] = moq_m.group(0).strip()
            products.append(entry)
            if len(products) >= 5:
                break

        return products

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
