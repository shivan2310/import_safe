# ImportSafe — Current State

## Current phase

P1 + P2 completed (commit 26a050a). P3/P4 not started.

## Current architecture

Frontend → `POST /api/v1/analyze` → FastAPI → TinyFish → extraction → normalization → response

Live retrieval failing (or `mode: "demo"`) → labelled demo fixture instead (never presented as live).

## Important interfaces (backend/app/schemas.py unless noted)

**AnalyzeRequest**: `url: str`, `mode: "live" | "demo"` (default `"live"`).

**AnalyzeResponse**:
- `mode` — upper-case retrieval mode ("LIVE"/"DEMO"); kept for the frontend badge
- `retrieval_mode` — `"live"` | `"demo"`
- `product` — normalized Product
- `missing_fields: list[str]` — tracked Product fields that are null
- `fallback_reason: str | None` — set when demo data was used (e.g. `tinyfish_not_configured: ...`)
- `raw` — RawEvidence dump

**Product** (all optional except `source_url`; unknown stays null):
`title, seller, price, price_max, currency, moq (int), description, specifications (dict[str,str]),
model, material, voltage, bluetooth, wifi, battery, battery_type, certification_claims (list[str]),
certification_claims_basis` (always `"SELLER_CLAIM"`), `image, source_url`.
Price ranges: `price` = low, `price_max` = high. Bare `$` leaves `currency` null.

**RawEvidence** (backend/app/services/extraction/extractor.py): `requested_url, retrieval_mode,
provider` ("tinyfish" | "demo_fixture"), `run_id, status, retrieved_at, raw_result, fallback_reason`.

**Errors**: HTTP body `{"detail": {"code", "message"}}`; codes: `invalid_url` (422),
`tinyfish_not_configured` (503), `tinyfish_failure` (502), `page_unavailable` (422),
`incomplete_extraction` (422). Invalid URLs never fall back to demo.

Other endpoint: `GET /health` → `{"status": "ok"}`.

## Existing backend modules (backend/app/)

- `main.py` — FastAPI app, CORS, error handler
- `api/routes.py` — `/health`, `/api/v1/analyze` (live/demo/fallback orchestration)
- `config.py` — env var accessors (loads `.env`)
- `errors.py` — `ImportSafeError` subclasses with HTTP status + code
- `schemas.py` — request/response/Product models
- `services/tinyfish/client.py` — TinyFish sync run client (`POST /v1/automation/run`, `X-API-Key`)
- `services/extraction/` — `goal.py` extraction prompt, `urls.py` URL validation, `extractor.py` raw evidence, `demo.py` Bluetooth-headphones fixture
- `services/normalization/normalizer.py` — raw result → Product + missing fields
- `backend/tests/test_extraction.py` — mocked-TinyFish tests (`python -m pytest -q`)

## Existing frontend structure (frontend/src/)

- `App.tsx` — URL input, Analyze button, result card (shows title, seller, price, MOQ, source, mode badge)
- `api.ts` — `analyze(url)` fetch + TS types (only a subset of Product; not yet updated for P2 fields)
- `main.tsx`, `index.css` — bootstrap and plain CSS (no Tailwind yet)

## Environment variables (names only)

Backend (`backend/.env`): `CORS_ORIGINS`, `TINYFISH_API_KEY`, `TINYFISH_BASE_URL`,
`TINYFISH_TIMEOUT_S`, `ALLOW_DEMO_FALLBACK`.
Frontend (`frontend/.env`): `VITE_API_BASE_URL`.

## Current limitations

- no HS classification yet
- no BIS/WPC compliance engine yet
- no independent certificate verification yet
- no tariff/landed cost yet
- no final risk engine yet
- TinyFish `/v1/automation/run` path is inferred from docs; not yet verified against a live key
- frontend displays only a few Product fields

## Next task

P3.1: Build HS classification using the normalized Product object.

P3.1 should NOT need to inspect TinyFish internals — consume `Product` only
(new module under `backend/app/services/classification/`).
