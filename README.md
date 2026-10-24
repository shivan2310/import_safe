# ImportSafe — "Can I Import This?"

**Smart import risk checks for Indian buyers.** Paste a product URL (from Alibaba or anywhere), answer a few questions, and get a complete import risk report with evidence, costs and next steps.

HackIIITD 2026 · Team Vinland Crusaders

---

## The Problem

When you import something from abroad, surprises come late:
- **BIS/WPC approvals** — will your gadget be blocked at customs?
- **Duties and taxes** — how much will actually land on your desk?
- **Fake certificates** — is the seller's "BIS certified" claim real?
- **Hidden costs** — freight, landing charges, import taxes all add up.

By the time you find out, you've already paid the supplier.

## What ImportSafe Does

1. **Paste a product URL** → We fetch and read the listing
2. **Ask a few quick questions** → Model number, quantity, destination, intent to resale or personal use
3. **Run automated checks** → HS classification, BIS/WPC rules, certificate matching, landed cost
4. **Get a risk report** → Import status (Likely Safe / Conditional / High Risk), with evidence and next actions
5. **Export and act** → Copy a seller request checklist or export the full report

**Every claim in the report traces back to evidence.** Missing data is marked as unknown, never guessed.

---

## How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│  YOU (Browser)                                                  │
│  Paste URL + answer questions → Click "Investigate"            │
└────────────────────────────┬──────────────────────────────────────┘
                             │
                  ┌──────────▼──────────┐
                  │  FRONTEND (React)  │
                  │  - Form            │
                  │  - Progress bars   │
                  │  - Risk report     │
                  └──────────┬──────────┘
                             │
                  ┌──────────▼──────────────┐
                  │  BACKEND (FastAPI)     │
                  │  - Extract product     │
                  │  - Check HS code       │
                  │  - Verify certificates │
                  │  - Calculate cost      │
                  │  - Generate report     │
                  └──────────┬──────────────┘
                             │
            ┌────────────────┼────────────────┐
            │                │                │
    ┌───────▼────┐  ┌────────▼────┐  ┌──────▼──────┐
    │ TinyFish   │  │ Official    │  │ Demo        │
    │ (live web) │  │ registries  │  │ fixtures    │
    │            │  │ (BIS, etc)  │  │ (fallback)  │
    └────────────┘  └─────────────┘  └─────────────┘
```

---

## Quick Start

### 1. Backend Setup

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

Then edit `.env` and add a TinyFish API key (free tier):
```
TINYFISH_API_KEY=your_key_here
```

Run:
```bash
python -m uvicorn app.main:app --port 8000
```

Test with: `python -m pytest -q` (no key needed — uses demo data)

### 2. Frontend Setup

```bash
cd frontend
npm install
copy .env.example .env
npm run dev
```

Then open `http://localhost:5173` in your browser.

### 3. Try the Demo

Click **"Try demo: 100 Bluetooth speakers"** to see the full flow without a real product URL.

---

## What's Built (Phase 1 & 2)

✅ **Product extraction** — Title, seller, price, specs, model, certification claims from live pages  
✅ **Evidence tracking** — Every fact keeps its source URL and retrieval time  
✅ **No invented data** — Missing values stay "unknown"; never guessed  
✅ **Six-stage progress** — Live updates as the investigation runs  
✅ **Follow-up questions** — Asks for missing model numbers, certificate details  
✅ **Live + Demo mode** — Real data when TinyFish works, cached fixtures as fallback  

---

## Architecture

| Layer | Job | Tools |
|-------|-----|-------|
| **Frontend** | Form, progress, risk report, export | React, Vite, TypeScript, Tailwind |
| **Backend** | Extract, classify, verify, cost, risk | Python, FastAPI, Pydantic |
| **Data sources** | Product pages & official registries | TinyFish API, demo fixtures |

**Design principle:** Backend owns all logic. Frontend just displays results. Every claim has evidence.

---

## Project Structure

```
frontend/          React + Vite app
  src/
    pages/         NewInvestigation, Investigation, Report, History
    components/    Form, progress, badges, cost panel, etc.
    api/           Mock backend (for now) + real API client
    types.ts       Shared TypeScript interfaces

backend/           FastAPI app
  app/
    main.py        Server entry
    routes.py      /health, /api/v1/analyze
    schemas.py     Request/response types
    services/      TinyFish, extraction, normalization
  tests/           Tests (mocked TinyFish)

docs/
  STATE.md         Current architecture & limits
```

---

## Features in Detail

### Product Extraction
- Reads live Alibaba/foreign product listings via TinyFish
- Extracts: title, seller, price, currency, MOQ, specs, model, material, certifications
- Falls back to demo fixture if page is blocked or TinyFish fails

### Requirement Checks
- **HS Classification** — what customs code does this product belong in?
- **BIS approval** — is it required? Is the claim verified?
- **Wireless approval (WPC)** — does this device need it?
- **Certificates** — are seller claims matched against official records?

### Cost Breakdown
- Goods value (FOB) → Freight → Insurance → Duties → Taxes → Final landed cost
- Shows **low / expected / high** ranges (accounting for uncertain rates and FX)
- All assumptions shown and editable
- Label: "Illustrative estimate, not a quote"

### Risk Report
- **Outcome:** Likely Safe / Conditional / High Risk / Insufficient Data
- **Risk level:** Low / Medium / High
- **Next action:** What to do before ordering
- **Evidence drawer:** Every source with URL and retrieval time

---

## Limitations (Phase 1 & 2)

❌ HS classification not yet live (backend ready, demo data only)  
❌ BIS/WPC compliance engine not yet live (demo statuses only)  
❌ Certificate verification not yet live (shows as "unverified")  
❌ Landed cost calculations using placeholder rates (demo only)  
❌ No "enter details manually" fallback for blocked pages  

These are built in **Phase 3 & 4** — in progress.

---

## Tech Stack (All Free)

- **Frontend:** React 18, Vite 5, TypeScript, Tailwind 3, React Router, TanStack Query v5, Lucide icons
- **Backend:** Python 3.9+, FastAPI, Pydantic, HTTPX, pytest
- **APIs:** TinyFish (free tier for web extraction)
- **Database:** None yet (Phase 3)

---

## Roadmap

| Phase | What | Status |
|-------|------|--------|
| **P1** | Form, progress UI, mock report | ✅ Done |
| **P2** | TinyFish extraction, normalization | ✅ Done |
| **P3** | HS classification, compliance rules, certificate matching | 🚧 Next |
| **P4** | Landed cost, risk scoring, export, history | 📋 Planned |

---

## Demo Scenario

**Input:**  
- Product: Alibaba Bluetooth speaker  
- Quantity: 100  
- Purpose: Resale  
- Destination: Delhi  

**Output:**  
- **Outcome:** Conditional Import  
- **Risk:** HIGH (requires verification)  
- **Why:** BIS approval needed but claim is unverified, wireless approval check required  
- **Next action:** Pause purchase, get correct certification evidence, resolve wireless requirement  
- **Cost:** ~₹1,850/unit (with visible assumptions and ranges)  

---

## Important Notes

### Security
- URLs validated (no internal IPs, no SSRF)
- TinyFish key is server-side only
- All page text treated as data (never executed)
- All user input sanitized

### Privacy
- No accounts needed (session-only MVP)
- Investigations auto-expire after 30 days
- DELETE removes all evidence and data

### Accuracy
- Every conclusion linked to evidence URL and rule version
- Unknowns marked as such (not guessed)
- No "fraud" or "fake" language — only "potential mismatch" and "unverified"

---

## Support & Docs

- **Architecture details:** See `docs/STATE.md`
- **API endpoints:** See backend README
- **Issues:** Check [GitHub](https://github.com/shivan2310/import_safe)

---

**ImportSafe is decision support. It is not legal clearance, customs approval or a duty quote.**
