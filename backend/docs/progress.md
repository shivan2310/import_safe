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

## Step 2 follow-up: staleness and versioning

**Purpose:** detect out-of-date assumption values and stamp every estimate with the assumptions version. Rules: `docs/decisions.md` section 5a.

**Files changed**
- `app/decision/cost_assumptions.yaml` — added `version` and `effective_date`, and `max_age_days` on every entry (proposed values); no rate, `verified` or owner changed.
- `app/decision/cost_config.py` — `max_age_days` (positive strict int), strict ISO `as_of` validation, required `version`/`effective_date` exposed as read-only properties, `parse_as_of` helper and `Date` alias.
- `app/decision/cost_engine.py` — optional `today` argument; per-entry `stale`, `age_days`, `max_age_days`; estimate fields `any_stale`, `staleness_checked`, `assumptions_version`, `assumptions_effective_date`.
- `tests/test_cost_engine.py` — new tests appended; existing tests unchanged.
- `docs/decisions.md` — appended section 5a.
- `docs/progress.md` — appended this section.

**Tests added:** 57 test cases (including parametrized cases) in `tests/test_cost_engine.py`, 57 passed, 0 failed.
**Full suite:** 139 passed, 0 failed (82 before this change). The golden case is unchanged: INR 154,287.59 total, INR 1,542.88 per unit.

Nothing outside the files listed above was modified in this follow-up.

## Rate evidence and approval

**Purpose:** gather rate evidence into pending proposals, have a person approve or reject each one, and let only approved values reach the cost engine. Rules: `docs/decisions.md` section 7. No live fetcher, scheduler, HTTP endpoint or database exists; fetching uses a fixture fetcher in tests.

**Files created**
- `app/decision/rates/__init__.py` — empty package marker.
- `app/decision/rates/provenance.py` — `Provenance` and `EvidenceKind` enums (leaf module, avoids an import cycle).
- `app/decision/rates/models.py` — candidates, check results, evidence packs, proposals, rejections, approved records, store events, pack hash.
- `app/decision/rates/policy.yaml` — per-rate policy and refresh budgets (all proposed, to confirm).
- `app/decision/rates/policy.py` — validated policy model and loader.
- `app/decision/rates/checks.py` — pure checks (tiers, unit, bounds, number in excerpt, dates, change, benchmark statistics).
- `app/decision/rates/builder.py` — pure `build_proposal` returning a proposal, rejection or unchanged result.
- `app/decision/rates/store.py` — append-only JSON-lines event store with `StoreCorruptionError`.
- `app/decision/rates/data/.gitignore` — keeps the local event log out of git.
- `app/decision/rates/fetcher.py` — `RateFetcher` protocol and `FixtureFetcher`.
- `app/decision/rates/updater.py` — `refresh_rates` (proposals, rejections, supersession, fetch errors, budgets).
- `app/decision/rates/review.py` — review functions and the `list` / `show` / `approve` / `reject` CLI.
- `app/decision/rates/loader.py` — `load_assumptions_with_store` and `load_assumptions_report`.
- `tests/rate_helpers.py` — shared test fixtures (not a test module).
- `tests/test_rate_checks.py`, `tests/test_rate_builder.py`, `tests/test_rate_store.py`, `tests/test_rate_updater.py`, `tests/test_rate_review.py`, `tests/test_rate_loader.py` — new tests.

**Files changed**
- `app/decision/cost_config.py` — `provenance`, `evidence_kind`, `evidence_note`, `range_low`/`range_high` on assumptions (ranges only on non-duty entries), `RANGE_FIELDS`, `verified_counts()`.
- `app/decision/cost_engine.py` — copies provenance and evidence kind to entries, uses non-duty ranges in the low/high scenarios when both bounds are set, adds `any_human_approved`, `rates_verified_count`, `rates_total`.
- `docs/decisions.md` — appended sections 6 (placeholder) and 7.
- `docs/progress.md` — appended this section.

**Tests added:** 204 (test_rate_checks 81, test_rate_builder 51, test_rate_review 23, test_rate_loader 21, test_rate_updater 16, test_rate_store 12), 204 passed, 0 failed.
**Full suite:** 343 passed, 0 failed (139 before this change). Existing tests are textually unchanged. The golden case is unchanged: INR 154,287.59 total, INR 1,542.88 per unit, including when loaded through the store with the YAML values.

Nothing outside the files listed above was modified in this step.

## Rate approval follow-up: fallback note, fixture safety, housekeeping

**Files changed**
- `app/decision/rates/models.py` — `Candidate.is_fixture`, `SourceRef.fixture`, `EvidencePack.fixture_data`, `RateRecord.fixture` and `fallback_note`, `ProposalApproved.fixture_allowed`.
- `app/decision/rates/fetcher.py` — `FixtureFetcher` marks returned candidates as fixture data.
- `app/decision/rates/builder.py` — carries the fixture flag into sources and the pack.
- `app/decision/rates/store.py` — sets the fallback note and warning when a newer approval is ignored.
- `app/decision/rates/loader.py` — adds the fallback sentence and fixture marker to entry notes; warns on fixture-approved records.
- `app/decision/rates/review.py` — `show` labels fixture data; `approve` refuses it without `--allow-fixture`.
- `app/decision/cost_assumptions.yaml` — restored the header comment ("nothing in this file is an official rate"); no value changed.
- `CLAUDE.md` (backend) — added rules: absolute or `backend/` paths for writes, `pwd` before appending, Python 3.10+ compatibility.
- `docs/decisions.md` — section 5a note on placeholder `as_of`; section 7 "Additions (after review)".
- `tests/rate_helpers.py` — the `approve` helper takes `allow_fixture` (default False).
- `tests/test_rate_updater.py` — two calls now pass `allow_fixture=True` (they approve fixture proposals); no expected value changed.

**Files created:** `tests/test_rate_fixture_and_fallback.py` — 14 tests, 14 passed.
**Full suite:** 357 passed, 0 failed (343 before). The golden case is unchanged: INR 154,287.59 total, INR 1,542.88 per unit.

Nothing outside the files listed above was modified in this follow-up.
