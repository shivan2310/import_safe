# ImportSafe Backend — Decisions

This file overrides `docs/prd-backend.md` wherever they conflict.

## 1. Enums

All enum values are lowercase snake_case. Code lives in `app/decision/enums.py`.

| Enum | Values |
|---|---|
| CheckStatus | potentially_applicable, verified, not_applicable, unverified, contradiction_detected |
| ClassificationStatus | confirmed, needs_confirmation, unsupported |
| FieldMatch | match, partial, mismatch, unknown |
| IdentityResult | verified, unverified, contradiction_detected |
| FactKind | confirmed, seller_claim, user_supplied |
| Confidence | high, medium, low |
| Outcome | likely_importable, conditional_import, high_risk_do_not_proceed, insufficient_information |
| RiskLevel | low, medium, high |
| StageState | pending, running, done, needs_input, failed |

These replace the PRD report-example values (`verification_required`, `check_required`,
`unresolved`, and `needs_confirmation` used as a check status). Friendly UI labels are a
frontend concern.

## 2. Outcome precedence

First match wins:

1. Any import prohibition applies -> `high_risk_do_not_proceed`, risk `high`.
2. Classification `unsupported`, or key facts missing and skipped -> `insufficient_information`;
   list the open questions.
3. Any `contradiction_detected` on a mandatory check -> `conditional_import`, risk `high`.
4. Any mandatory check `potentially_applicable` or `unverified` -> `conditional_import`, risk by score.
5. Otherwise -> `likely_importable`, risk `low`.

`needs_confirmation` does NOT trigger rule 2. It adds a score point and a follow-up question,
and the investigation continues.

## 3. Risk score

Weights live in `app/decision/risk_weights.yaml`, never in code.

| Factor | Points |
|---|---|
| contradiction_detected | 3 each |
| unverified | 2 each |
| potentially_applicable | 1 each |
| purpose is resale | +1 |
| quantity >= 50 (configurable) | +1 |
| classification needs_confirmation | +1 |

Levels: low 0-1, medium 2-4, high 5+. Any contradiction forces high.

Worked demo: BIS potentially_applicable (1) + wireless potentially_applicable (1) +
identity unverified (2) + resale (1) + quantity 100 (1) + classification needs_confirmation (1)
= 7 -> high.

## 4. Open decisions

Listed, not resolved:

- Default cost assumptions, and who owns/verifies them.
- Live vs user-supplied registry checks.
- Session handling and ID scheme.
- API path reconciliation: existing `/api/v1/analyze` vs PRD `/api/investigations`.
- Converting `app/schemas.py` and `app/config.py` into packages.
- The TinyFish endpoint path is unverified.
- HS candidate-based rate variation not implemented; BCD range stands in.

## 5. Cost assumptions

Code: `app/decision/cost_config.py`, `app/decision/cost_engine.py`. Values: `app/decision/cost_assumptions.yaml`.

**Nothing in the shipped YAML is an official rate.** Every value is a PLACEHOLDER with
`verified: false` and `owner: TBD`. Each rate is a configurable assumption carrying `value`,
`source`, `as_of` and `verified`.

`verified` means checked against an official source. A user-supplied override is recorded with
source "user override", `verified: false` and `user_supplied: true`; it never clears the
unverified warning. `all_verified()` and the `unverified_assumptions` flag depend on `verified`
only.

The label **"Illustrative estimate, not a quote."** is mandatory on every cost output.

### Calculation order (Decimal throughout)

1. goods value = unit price x quantity x FX (FX is 1 for INR prices)
2. CIF = goods + freight + insurance
3. assessable value = CIF + landing charge (landing charge = % of CIF)
4. BCD = BCD rate x assessable value
5. SWS = SWS rate x BCD
6. other duties, each on its own base (empty by default)
7. IGST = IGST rate x (assessable value + BCD + SWS + other duties)
8. non-duty costs: clearing, port/CFS, domestic transport, certification/testing
9. landed cost = goods + freight + insurance + BCD + SWS + other duties + IGST + non-duty costs

### Decisions (to verify)

- **Landing charge is NOTIONAL (to verify):** it is added to the assessable value only and is NOT
  added to landed cost.
- Percentages are plain numbers (20 means 20%); field names carry `_pct`.
- Missing freight: the labelled default freight range is used; expected is the midpoint; an
  assumption entry says so. Missing insurance falls back to `insurance_pct_of_goods` x goods with
  an assumption entry.
- Range: low/high vary BCD (`bcd_low_pct` / `bcd_high_pct`), FX and freight by the configured
  percentages. Everything else stays at base values. Expected uses base values.
- Rounding: full Decimal precision internally (28 digits, fixed via a local context), quantized to
  0.01 INR with ROUND_HALF_UP on final outputs only. Per-unit values come from the unrounded total.
- Currency: USD and INR only. FX rates are never fetched.
- Float inputs are rejected; int, str and Decimal are accepted. YAML numbers are converted with
  `Decimal(str(value))` before validation.

### Additions (after review)

- **Section 5 overrides PRD B9 on landing charge treatment** (flagged "to verify"). B9 adds landing
  charges to landed cost; Section 5 treats the landing charge as notional (assessable value only).
- **Cost flags.** `CostEstimate` exposes: `rates_verified` (every config rate is verified, i.e.
  `all_verified()`, and no override or derived default is in use); `methodology_unverified` (true
  while the notional landing charge and the SWS and IGST bases are marked "to verify"; the set is
  `METHODOLOGY_TO_VERIFY` in `cost_engine.py`); `unverified_assumptions` (any assumption entry
  unverified; it does not clear while methodology items remain "to verify").
- **Breakdown rounding.** Breakdown lines are rounded individually and may differ by a cent from the
  total. Consumers must use the engine total (`low`, `expected`, `high`), not the sum of the lines.
  `CostEstimate.breakdown_note` carries this text.
