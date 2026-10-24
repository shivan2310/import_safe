# Backend Progress — Steps 1 and 2

Factual summary of what exists in `backend/` now. Paths are relative to `backend/`.

## Step 1 — Decisions, shared enums, risk config

**Purpose:** record the decision rules and provide the shared enums and a validated, configurable risk-score setup. No scoring code exists yet.

**Files created**
- `docs/decisions.md` — decisions (sections 1–4 from Step 1, section 5 from Step 2).
- `CLAUDE.md` — backend-only rules that add to the root `CLAUDE.md`.
- `app/decision/__init__.py` — empty package marker.
- `app/decision/enums.py` — nine `str, Enum` classes (CheckStatus, ClassificationStatus, FieldMatch, IdentityResult, FactKind, Confidence, Outcome, RiskLevel, StageState).
- `app/decision/risk_weights.yaml` — risk weights, bonuses, quantity threshold, score ranges.
- `app/decision/risk_config.py` — Pydantic v2 model and loader; rejects negative weights, gaps, overlaps, a closed high range and missing weights.
- `tests/test_decision_enums_config.py` — enum and risk-config tests.

**Files changed:** `requirements.txt` (appended `pyyaml>=6.0`).

**Tests added:** 18 (`tests/test_decision_enums_config.py`), 18 passed, 0 failed.

## Step 2 — Cost assumptions and pure cost engine

**Purpose:** configurable cost assumptions and a pure function that estimates landed cost. No endpoint, database, FX fetching, rule, risk or verification code exists.

**Files created**
- `app/decision/cost_assumptions.yaml` — placeholder rates and range settings (all `verified: false`, owner TBD).
- `app/decision/cost_config.py` — Pydantic v2 models with `Decimal` values, float rejection, loader that converts numbers with `Decimal(str(value))`, and `all_verified()`.
- `app/decision/cost_engine.py` — `estimate_cost(inputs, assumptions) -> CostEstimate`, plus input, override, breakdown and assumption models.
- `tests/test_cost_engine.py` — golden case and behaviour tests.

**Files changed:** `docs/decisions.md` (appended section 5). `requirements.txt` was not changed in this step.

**Tests added:** 59 (`tests/test_cost_engine.py`), 59 passed, 0 failed.
**Full suite:** 82 passed, 0 failed (5 existing P1/P2 tests included).

## Decisions recorded in `docs/decisions.md`

1. Enum values (nine enums, lowercase snake_case); they replace the PRD report-example values.
2. Outcome precedence (five rules, first match wins); `needs_confirmation` does not trigger rule 2.
3. Risk score weights live in config; any contradiction forces high; worked demo scores 7 -> high.
4. Open decisions (listed below).
5. Cost assumptions:
   - calculation order and the mandatory label "Illustrative estimate, not a quote."
   - the landing charge is notional (assessable value only, not added to landed cost) — marked to verify
   - `verified` means checked against an official source; user overrides are `user_supplied`, never `verified`
   - percentages are plain numbers; missing freight uses a labelled default range with the midpoint as expected; missing insurance falls back to a percentage of goods
   - 28-digit Decimal context, rounding to 0.01 INR (ROUND_HALF_UP) on final outputs only; USD and INR only
   - Section 5 overrides PRD B9 on landing charge treatment (to verify)
   - flags on `CostEstimate`: `rates_verified`, `methodology_unverified` (landing charge, SWS and IGST bases "to verify"), and `unverified_assumptions`, which never clears while methodology items are unverified
   - breakdown lines may differ by a cent from the total; consumers use the engine total, not the sum of lines (`breakdown_note`)

## Unverified assumptions (all placeholders)

Every value below is a placeholder and not an official rate. `verified: false`, owner TBD, source "placeholder - not verified", as_of 2026-10-24.

| Assumption | Placeholder |
|---|---|
| fx_usd_inr | 90 |
| landing_charge_pct | 1 |
| bcd_pct | 20 |
| sws_pct_of_bcd | 10 |
| igst_pct | 18 |
| insurance_pct_of_goods | 0 |
| clearing_inr | 3000 |
| port_cfs_inr | 2000 |
| domestic_transport_inr | 2000 |
| certification_inr | 0 |
| other_duties | none (empty list) |
| fx_variation_pct | 5 |
| freight_variation_pct | 20 |
| bcd_low_pct | 10 |
| bcd_high_pct | 30 |
| default_freight_low_inr | 5000 |
| default_freight_high_inr | 20000 |

The landing-charge treatment and the SWS and IGST bases are also unverified methodology decisions (section 5).

## Golden case versus the PRD illustration

Inputs: USD 10 per unit, quantity 100, freight INR 12,000, insurance 0, placeholder assumptions.
Result: landed cost INR 154,287.59, **INR 1,542.88 per unit**.

The PRD (section 6) illustrates about INR 1,850 per unit for its demo case. The golden case is INR 307.12 per unit lower (about 17%). This is a gap, not a bug: the PRD gives no inputs behind its figure, and no assumption was tuned to reach 1,850. Closing the gap needs real inputs and verified rates.

## Open decisions still pending (from `docs/decisions.md` section 4)

- Default cost assumptions, and who owns/verifies them.
- Live vs user-supplied registry checks.
- Session handling and ID scheme.
- API path reconciliation: existing `/api/v1/analyze` vs PRD `/api/investigations`.
- Converting `app/schemas.py` and `app/config.py` into packages.
- The TinyFish endpoint path is unverified.
- HS candidate-based rate variation not implemented; BCD range stands in.

## Not modified

The existing P1/P2 code, `frontend/`, root `CLAUDE.md`, `README.md`, `docs/STATE.md` and `docs/prd-backend.md` were not modified.

## Next step

Step 3: verification engine.
