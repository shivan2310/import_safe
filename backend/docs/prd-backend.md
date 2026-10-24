# ImportSafe – Backend PRD (extracted from Product Requirements Document v1.0)

Team Vinland Crusaders · HackIIITD Round 1 · Version 1.0 (24-hour MVP)

> Extracted from the original PRD: Part B (B1–B12) plus sections 6–10. Wording is kept as in the source.
> NOTE: `docs/decisions.md` overrides this file wherever they conflict.

**Product context:** ImportSafe is a pre-import risk intelligence tool for Indian buyers. The buyer pastes a product link (e.g., an Alibaba listing) and answers a few order questions. ImportSafe investigates that specific product and order, then returns a risk report covering import restrictions, certification claims, landed cost and recommended next actions.

**Core principle:** Every conclusion traces to evidence (URL, retrieval time, excerpt, rule version) or is explicitly marked as an assumption. Unknowns are surfaced as questions, never guessed.

**Disclaimer (shown on every report):** ImportSafe is decision support. It is not legal clearance, customs approval or a duty quote.

---

# PART B – BACKEND PRD

## B1. Stack and Architecture

Suggested stack: Python FastAPI (or Node/NestJS), PostgreSQL (JSONB for profiles and evidence), Redis + a job queue (RQ, Celery or BullMQ), object storage for raw page snapshots, TinyFish API for live web extraction.

LLM usage (optional, constrained): Only for turning extracted page text into a structured product profile and for drafting plain-language explanations. Classification outcomes, rule matching, identity comparison, cost and risk are deterministic code so results are auditable.

### Modules (matching the deck's application structure)

| Module | Responsibility |
|---|---|
| API layer | Auth-less MVP session handling, validation, rate limiting |
| Investigation coordinator | Creates jobs, orchestrates TinyFish tasks, retries, timeouts, state machine, emits progress events |
| TinyFish connector | Runs extraction tasks for the listing and official registration portals; normalises output |
| Product profile builder | Normalises facts; tags each field as Confirmed / Seller claim / User-supplied; attaches provenance |
| Category rule engine | Classifies product; loads versioned rule set; produces requirement checks |
| Verification engine | Compares seller certification claims to registration records (identity match) |
| Cost engine | Computes landed cost using correct assessment bases and ranges |
| Risk engine | Combines checks and cost into outcome, risk level and actions |
| Evidence store | Persists URLs, timestamps, excerpts, rule versions, raw snapshots |

## B2. Investigation State Machine

```
CREATED → READING_LISTING → PROFILE_BUILT → (NEEDS_INPUT ⇄ PROFILE_BUILT) →
CLASSIFIED → CHECKING_REQUIREMENTS → VERIFYING_CLAIMS → ESTIMATING_COST →
REPORT_READY
```

Terminal alternatives: `FAILED`, `CANCELLED`, `EXPIRED`, `DELETED`. Every transition writes an event for the progress stream. Each stage has a timeout and a limited retry count (e.g., 2 retries with backoff).

## B3. API Specification

### POST /api/investigations

Request:

```json
{
  "url": "https://www.alibaba.com/product-detail/...",
  "quantity": 100,
  "destination": { "state": "Delhi", "city": "New Delhi" },
  "purpose": "resale",
  "variant": "Black, 20W",
  "shipping": { "amount": 12000, "currency": "INR", "mode": "air" },
  "sellerCertificates": ["R-41234567"]
}
```

Response `201`: `{ "id": "inv_123", "status": "CREATED" }`

Errors: `400` invalid input, `422` URL rejected (internal address, unsupported scheme), `429` rate limit.

### GET /api/investigations/{id}

Returns current status, stage list, pending question (if any), and timestamps.

### GET /api/investigations/{id}/events

SSE stream of `{ stage, state, message, at }`.

### POST /api/investigations/{id}/answers

`{ "questionId": "q_1", "value": "BT-100" }` or `{ "questionId": "q_1", "skipped": true }`

### PATCH /api/investigations/{id}/assumptions

Update freight, exchange rate, duty rate overrides, insurance, other charges. Triggers cost recalculation only.

### GET /api/investigations/{id}/report

Returns the full report object (see B5).

### DELETE /api/investigations/{id}

Hard-deletes the investigation, evidence and snapshots.

### Frontend API usage (for reference)

| Action | Call |
|---|---|
| Start investigation | POST /api/investigations |
| Subscribe to progress | GET /api/investigations/{id}/events (SSE) or poll GET /api/investigations/{id} |
| Answer follow-up | POST /api/investigations/{id}/answers |
| Update cost assumptions | PATCH /api/investigations/{id}/assumptions then re-fetch cost |
| Fetch report | GET /api/investigations/{id}/report |
| Delete | DELETE /api/investigations/{id} |

## B4. Data Model (PostgreSQL)

- **investigations** — id, url, normalized_url, quantity, destination, purpose, variant, status, created_at, expires_at, deleted_at
- **order_inputs** — investigation_id, shipping_amount, shipping_currency, shipping_mode, insurance, other_charges, fx_rate, fx_source, fx_time
- **product_profiles** — investigation_id, version, category, category_confidence, profile (JSONB)
- **facts** — id, investigation_id, field, value, kind (`confirmed` | `seller_claim` | `user_supplied`), evidence_id, confidence
- **evidence** — id, investigation_id, source_url, retrieved_at, excerpt, snapshot_ref, source_type (`listing` | `official_portal` | `user_upload` | `rule_source`)
- **rule_sets** — id, category, version, effective_date, source_urls, rules (JSONB)
- **requirement_checks** — id, investigation_id, rule_id, rule_version, area (`import_policy` | `bis` | `wireless` | `battery` | `labelling` | `category_specific`), status, reasoning, evidence_ids
- **certification_comparisons** — id, investigation_id, claim_registration_no, record_registration_no, field_results (JSONB), result, evidence_ids
- **cost_estimates** — id, investigation_id, assumptions (JSONB), breakdown (JSONB), low, expected, high, per_unit_expected
- **reports** — investigation_id, outcome, risk_level, next_actions (JSONB), generated_at, rule_set_versions
- **questions** — id, investigation_id, field, prompt, why_it_matters, answer, status

## B5. Report Object (response shape)

```json
{
  "id": "inv_123",
  "outcome": "CONDITIONAL_IMPORT",
  "riskLevel": "HIGH",
  "nextAction": "Pause the purchase. Get the correct certification evidence and resolve the wireless requirement before ordering.",
  "summary": {
    "quantity": 100,
    "classification": { "value": "Bluetooth speaker", "status": "needs_confirmation" },
    "bis": "verification_required",
    "wireless": "check_required",
    "sellerClaimsBis": true,
    "identityMatch": "unresolved",
    "illustrativeCostPerUnit": { "currency": "INR", "expected": 1850 }
  },
  "profile": { "confirmed": [], "sellerClaims": [], "userSupplied": [] },
  "checks": [
    { "area": "bis", "status": "potentially_applicable", "reasoning": "...",
      "ruleVersion": "v1.0", "evidenceIds": ["ev_1"] }
  ],
  "certificationComparison": null,
  "cost": { "low": 0, "expected": 0, "high": 0, "breakdown": [], "assumptions": [] },
  "evidence": [],
  "disclaimer": "Decision support only. Not legal clearance or customs approval."
}
```

## B6. TinyFish Integration

**Task A – Listing extraction:** Input URL; output name, category, variant, model, seller name, actual manufacturer (if shown), price, currency, MOQ, origin, specs (Bluetooth/Wi-Fi version, battery type and capacity), certification claims and numbers.

**Task B – Official evidence gathering:** For a given registration number or manufacturer + model, query the relevant official registry pages and return structured fields (registration no., manufacturer, factory location, category, model scope, brand, validity, status).

Every extracted fact is saved with source URL, retrieval timestamp and a supporting excerpt. Facts without an excerpt are downgraded to low confidence.

**Failure handling:** On block, timeout or incomplete data, mark the stage `NEEDS_INPUT` or `PARTIAL`, record the limitation, and create a follow-up question. Never invent values.

**Credentials:** TinyFish API key is server-side only, in environment variables.

**Untrusted content:** All page text is treated as data. It is delimited and never executed or treated as instructions. If an LLM is used for structuring, the prompt states that page content is untrusted, output is schema-validated, and extra fields are dropped.

## B7. Classification and Rule Engine

**Classification:** Map extracted category, title and specs to a supported product type using a deterministic keyword/attribute mapping with an optional LLM suggestion. Output: category, candidate HS code(s) as suggestions, confidence. Below a confidence threshold, status is `needs_confirmation` and a follow-up is raised.

**Rule format (versioned JSON/YAML):**

```json
{
  "id": "bt_speaker_bis_v1",
  "category": "bluetooth_speaker",
  "area": "bis",
  "condition": "category == 'bluetooth_speaker'",
  "result_if_true": "potentially_applicable",
  "requires_evidence": ["registration_record"],
  "source_urls": ["<official source>"],
  "version": "1.0",
  "effective_date": "2026-10-24",
  "last_reviewed": "2026-10-24"
}
```

Areas covered: import policy, BIS, wireless approval, battery, labelling, category-specific rules.

Rule content must be verified by the team against current official sources before the demo. Each rule stores its source link and review date. The report displays the rule version.

Status assignment follows the five statuses defined in the deck:

| Status | Meaning |
|---|---|
| Potentially applicable | Details indicate a requirement needing confirmation |
| Verified | Evidence supports the specific check |
| Not applicable | Facts and rule support this conclusion |
| Unverified | Evidence insufficient; not the same as fraud |
| Contradiction detected | Reliable evidence conflicts with a claim |

A check is **Verified** only when evidence supports that exact check; absence of evidence yields **Unverified**, never Contradiction.

## B8. Verification Engine (Certification Identity Match)

Compare claim vs record on: registration number, manufacturer name, factory location, category, model scope, brand, validity dates, status.

| Field result | Meaning |
|---|---|
| match | Normalised values equal (case, punctuation, legal suffix insensitive) |
| partial | Fuzzy match above threshold, flagged for review |
| mismatch | Reliable record contradicts claim |
| unknown | Value missing on either side |

Overall result:

- Any hard mismatch on model scope, manufacturer or validity with a reliable record → **Contradiction detected** (UI label: "potential certification mismatch").
- Record not accessible or fields unknown → **Unverified**.
- All required fields match and record is valid → **Verified**.

The output lists conflicting fields and generates a seller request list (e.g., "Ask the seller for the BIS licence/registration covering model BT-100 manufactured at FactoryA, with validity dates").

## B9. Cost Engine

**Principle:** different charges apply to different bases. All rates are configurable assumptions, shown to the user, with sources and dates. Verify against current customs tariff and notifications before the demo.

**Inputs:** unit price, quantity, currency, FX rate (source and timestamp), freight, insurance, other charges, candidate HS code and rates.

Typical Indian import calculation structure (to be validated):

1. Goods value (FOB) converted to INR.
2. Add freight and insurance to get CIF.
3. Add landing charges as configured (commonly a percentage of CIF) to get the assessable value.
4. Basic customs duty (BCD) = BCD rate × assessable value.
5. Social welfare surcharge (SWS) = configured rate × BCD.
6. Any additional duties applicable to the HS code (e.g., AIDC, anti-dumping) on their own bases.
7. IGST = IGST rate × (assessable value + BCD + SWS + other duties on the IGST base).
8. Add non-duty costs: clearing agent, port or CFS charges, domestic transport, certification or testing costs if required.
9. Landed cost = goods + freight + insurance + all duties and taxes + other charges.

Output per unit and total.

**Ranges:** Low / expected / high computed by varying uncertain inputs (candidate HS code rates, FX movement, freight). If freight or duty inputs are missing, use clearly labelled default ranges and mark them as assumptions.

**Output:** itemised breakdown with the base for each line, plus an assumptions list. Label: "Illustrative estimate, not a quote."

## B10. Risk Engine

**Inputs:** requirement check statuses, identity match result, classification confidence, evidence completeness, purpose (resale increases scrutiny), quantity.

Outcome mapping (initial deterministic scoring):

| Condition | Outcome |
|---|---|
| Any import prohibition applies | High Risk – Do Not Proceed |
| Any Contradiction detected on a mandatory requirement | Conditional Import, risk High, action: obtain correct evidence |
| Mandatory requirements Potentially applicable or Unverified | Conditional Import, risk Medium or High by count and severity |
| Mandatory requirements verified and no contradictions | Likely Importable, risk Low |
| Classification or key facts missing | Insufficient Information, with questions |

Each outcome includes the top reasons (linked to checks) and a prioritised next-action list. Scoring weights live in config so the team can tune them.

## B11. Security and Privacy

- **URL validation (SSRF protection):** allow only http/https; resolve DNS and block private, loopback, link-local and metadata IP ranges; re-check after redirects; cap redirects; block non-standard ports.
- Server-side credentials for TinyFish and any LLM; never exposed to the client.
- Timeouts and limited retries on every external call.
- Rate limiting per IP/session on investigation creation.
- Input sanitisation for all user fields; output escaping on the frontend.
- **Prompt-injection resistance:** page text cannot alter app behaviour; structured, schema-validated extraction only.
- **Evidence expiry:** investigations and snapshots auto-expire (e.g., 30 days); the report shows retrieval times so users know how fresh the data is.
- **User deletion:** DELETE removes all data for the investigation.
- **Logging:** log job and error metadata, not full page content or personal data.

## B12. Non-Functional Requirements

| Area | Target |
|---|---|
| End-to-end time (happy path) | Under 90 seconds for the demo cases (cache demo evidence as fallback) |
| Availability for demo | Pre-recorded fallback fixtures for demo URLs if live sources fail |
| Determinism | Same inputs and same rule versions produce the same outcome |
| Observability | Per-stage timing, error codes, TinyFish task IDs |
| Auditability | Every conclusion links to evidence IDs and rule version |

---

## 6. Demo Scenario (Acceptance Case)

**Input:** Alibaba listing, 100 Bluetooth speakers, resale, Delhi.

**Expected report:**

- Outcome: Conditional Import, overall risk High.
- Classification: requires confirmation. BIS: verification required. Wireless approval: check required.
- Seller claims BIS: yes. Model/manufacturer match: unresolved (or Contradiction if a mismatching record is supplied).
- Illustrative cost about ₹1,850 per unit with visible assumptions.
- Next action: pause the purchase, get correct certification evidence, resolve the wireless requirement.

## 7. Testing and Success Metrics

**Test cases:** complete listing · missing model · certificate for a different model · expired record · inaccessible portal · ambiguous classification · missing freight/duty inputs · unsupported claim · malicious page text (prompt injection) · internal-IP URL (SSRF).

**Metrics:**

- Extraction accuracy against hand-labelled fields.
- Identity-match correctness against labelled pairs.
- Citation coverage: percentage of report claims with evidence or an assumption tag (target 100%).
- Cautious handling of unknowns: percentage of missing-data cases that return Unverified or a follow-up rather than a guess (target 100%).

## 8. 24-Hour Build Plan and Task Split

Suggested ownership: one teammate on frontend, one on backend integrations (TinyFish, evidence, verification), one on rules, cost and risk logic plus testing and demo.

| Hours | Frontend | Backend |
|---|---|---|
| 0–4 | Project setup, design tokens, form and report skeleton with mock data | DB schema, rule file format, Bluetooth speaker rules, report schema, demo fixtures |
| 4–10 | Progress stepper with SSE, follow-up card, product profile view | TinyFish connector, listing extraction, evidence capture, official portal task |
| 10–17 | Requirement checks, certification comparison panel, cost panel with assumption editing | Classification, rule matching, verification engine, cost engine, risk engine, report endpoint |
| 17–24 | Error states, accessibility pass, responsive polish, demo flow | Failure testing, SSRF and injection tests, fallbacks, deploy, demo prep |

## 9. Risks and Mitigations

| Risk | Mitigation |
|---|---|
| Alibaba or official portals block or change layout | Cached fixtures for demo URLs; graceful Unverified fallback |
| Incorrect or outdated rules | Version and date every rule, link sources, team review before demo |
| Misleading cost numbers | Show ranges, assumptions and "not a quote" label; allow editing |
| Over-claiming (calling sellers fraudulent) | Language guardrails; Unverified is distinct from Contradiction |
| Scope creep beyond 24 hours | Hold to Bluetooth speakers plus one appliance subtype |
| LLM hallucination | Deterministic logic for decisions; schema-validated extraction; excerpts required |

## 10. Open Questions

1. Which official registries and portals will be queried live versus supplied by the user as a record or number?
2. Which small electrical appliance subtype will be the second supported category?
3. Will a PDF export be built, or is a print-friendly page enough for the demo?
4. Should users need accounts, or is a session-only MVP acceptable?
5. Which duty and tax rates and landing-charge percentage will be used as defaults, and who will verify them against current official notifications?
