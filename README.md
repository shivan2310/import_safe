# ImportSafe — "Can I Import This?"

HackIIITD 2026 · Team Vinland Crusaders

ImportSafe takes an Alibaba (or other foreign) product URL and is being built to help an Indian
buyer understand whether, and at what cost and risk, the product can be imported.

## Problem

Importers often find out about HS classification, BIS/WPC requirements, duties and fake or
unverifiable seller certificates only after money is committed. ImportSafe aims to surface this
up front with evidence, and to say "unknown" instead of guessing when evidence is missing.

## What works today (P1 + P2)

- Paste a product URL in the web UI and click Analyze.
- Backend fetches the page with TinyFish and extracts product data (title, seller, price, currency,
  MOQ, description, specifications, model, material, voltage, Bluetooth, Wi-Fi, battery, battery type,
  seller certification claims, image, source URL).
- Raw retrieval evidence and the normalized product are kept separately.
- Missing values stay null and are listed in `missing_fields`; nothing is invented.
- Certification claims are returned as unverified `SELLER_CLAIM`s.
- Clear error codes for invalid URL, TinyFish failure, unavailable page and incomplete extraction.
- LIVE and DEMO modes (a single sample Bluetooth-headphones product for demo reliability).

## Architecture

```
React frontend
→ POST /api/v1/analyze
→ FastAPI
→ TinyFish (live)  /  demo fixture (labelled)
→ raw evidence
→ normalization
→ product result
```

## Tech stack (all free)

- Frontend: React, Vite, TypeScript
- Backend: Python, FastAPI, Pydantic, HTTPX
- Retrieval: TinyFish (free-tier API key)

Planned: SQLite, Tailwind, React Router, TanStack Query.

## Folders

```
frontend/   React + Vite app
backend/    FastAPI app (app/), tests (tests/)
docs/       STATE.md — compact project state
CLAUDE.md   AI-assistant context and rules
```

## Setup

### Backend

```
cd backend
python -m venv .venv
.venv\Scripts\activate          # Windows; use source .venv/bin/activate elsewhere
pip install -r requirements.txt
copy .env.example .env          # then edit .env
python -m uvicorn app.main:app --port 8000
```

Tests: `python -m pytest -q` (uses a mocked TinyFish; no key needed).

### Frontend

```
cd frontend
npm install
copy .env.example .env          # VITE_API_BASE_URL=http://localhost:8000
npm run dev                     # http://localhost:5173
```

Production build check: `npm run build`.

### TinyFish key

Get a free API key from TinyFish and set it in `backend/.env`:

```
TINYFISH_API_KEY=<your key>
```

Never commit `.env`. Other backend variables: `TINYFISH_BASE_URL`, `TINYFISH_TIMEOUT_S`,
`ALLOW_DEMO_FALLBACK`, `CORS_ORIGINS` (see `backend/.env.example`).

## LIVE vs DEMO mode

- **LIVE** (default): the URL is retrieved through TinyFish.
- **DEMO**: send `"mode": "demo"`, or let the backend fall back when live retrieval fails or no key is
  set (`ALLOW_DEMO_FALLBACK=true`, the default). Demo responses have `retrieval_mode: "demo"`,
  `raw.provider: "demo_fixture"` and a `fallback_reason`; the UI badge reads "DEMO DATA".
  Demo data is a hand-written sample, never live data. Set `ALLOW_DEMO_FALLBACK=false` to surface
  real failures as errors instead.

## API summary

- `GET /health` → `{"status": "ok"}`
- `POST /api/v1/analyze` — body `{"url": "...", "mode": "live" | "demo"}`; returns `mode`,
  `retrieval_mode`, `product`, `missing_fields`, `fallback_reason`, `raw`.
  Errors: `{"detail": {"code", "message"}}` with `invalid_url`, `tinyfish_not_configured`,
  `tinyfish_failure`, `page_unavailable`, `incomplete_extraction`.

## Current limitations

- No HS classification, BIS/WPC compliance engine, independent certificate verification,
  tariff/landed-cost calculation or risk engine yet.
- The TinyFish endpoint path was taken from its docs and has not yet been verified with a live key.
- The UI shows only a few product fields.

## Roadmap

- **P3**: HS classification, compliance engine, certification/evidence.
- **P4**: landed cost, risk, pre-import checklist, report.
