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

## 5a. Staleness and versioning

Code: `app/decision/cost_config.py` (`max_age_days`, `version`, `effective_date`, `parse_as_of`),
`app/decision/cost_engine.py` (`estimate_cost(inputs, assumptions, today=None)`).

### Rule

- An assumption entry is **stale when its age exceeds `max_age_days`**; age = `today - as_of` in
  days. Exactly at the limit is NOT stale.
- `as_of` after `today` is not stale; the entry note says the `as_of` date is in the future.
- For placeholders, `as_of` is the date the placeholder was created, not the date of any official rate.
- Derived entries inherit staleness: the derived default `freight_inr` is stale if either
  default-freight source entry is stale; the derived `insurance_inr` is stale if
  `insurance_pct_of_goods` is stale. User overrides and methodology entries are never checked
  (`stale` stays null) and do not count toward `any_stale`.
- Entries without `max_age_days` (allowed only on `other_duties`) are not checked; the note says
  "no expiry set, staleness not checked".
- Staleness never changes any amount and does not feed `rates_verified`,
  `methodology_unverified` or `unverified_assumptions`.

### Proposed maximum ages (proposed, to confirm)

| Entry | max_age_days |
|---|---|
| fx_usd_inr | 20 |
| bcd_pct, sws_pct_of_bcd, igst_pct | 90 |
| landing_charge_pct | 180 |
| clearing_inr, port_cfs_inr, domestic_transport_inr, certification_inr, insurance_pct_of_goods | 90 |
| default_freight_low_inr, default_freight_high_inr | 90 |
| fx_variation_pct, freight_variation_pct, bcd_low_pct, bcd_high_pct (range settings; these are assumption entries) | 180 |

### Today's date and risk

- `today` is passed by the caller. The engine never reads the clock. With `today=None`,
  `staleness_checked` is false and no entry is checked.
- Staleness shows a warning only and does NOT affect the risk score (proposed).

### Versioning

- The YAML carries a required `version` (non-empty string) and `effective_date` (ISO date).
  Every estimate records them as `assumptions_version` and `assumptions_effective_date`.
- Old results are reproduced from git history: check out the YAML at the recorded version and
  rerun with the same inputs and `today`.

### Review routine (to be filled in by the team)

- Owner: TBD.
- FX: checked against the latest CBIC notification before the demo and about every fortnight.
- Duty rates: checked against the current tariff and notifications before the demo.
- Each check updates `as_of`, `source` and `verified` together.

### Open items

- Automatic FX provider.
- Making `today` required once the investigation flow supplies it.

Section 6: reserved for the verification step, not yet written.

## 7. Rate evidence and human approval

**Everything in this section is proposed, to confirm.** Code: `app/decision/rates/`. Numbers and domain lists:
`app/decision/rates/policy.yaml`.

### Pipeline

- TinyFish gathers candidates and evidence: each candidate carries its source URL, retrieval time and excerpt.
  The live TinyFish adapter is a later step; only a fixture fetcher exists, and no live network call is made.
- Pure checks turn candidates into **pending proposals** with an evidence pack (sources with tier and excerpt,
  agreement, disagreements, check results, warnings, content hash). A hard failure produces a logged
  `RejectionRecord`, never a proposal.
- A person approves or rejects each proposal. **Only approved values reach the cost engine**, through
  `load_assumptions_with_store()`, which builds the same `CostAssumptions` the engine already accepts. The engine
  itself still never reads the store, the clock or the network; Section 5's "FX rates are never fetched" still
  holds for the engine.
- An approval records the approver, time, note, acknowledged warnings and the evidence hash. The loader ignores
  an approval whose hash no longer matches its pack and reports a warning.

### What "verified" means

- For an approved record, `verified: true` means **a person checked the evidence pack**. For these records this
  replaces Section 5's "checked against an official source".
- `rates_verified` and `verified` **never mean "official"**. Consumers read `evidence_kind` (official or
  benchmark) and `provenance` (placeholder or human_approved).
- `rates_verified` keeps the Section 5 rule: true only when every config rate is verified. `CostEstimate` also
  reports `rates_verified_count`, `rates_total` and `any_human_approved`.

### Source tiers

- The tier comes from the policy domain lists only. A fetcher's claimed tier is advisory, and claiming a better
  tier than the policy gives is a warning. Hosts are normalised (lowercase, trailing dot removed, userinfo and
  port ignored) and match a listed domain exactly or as a subdomain. **Tier 1 also requires https.** Any other
  domain is tier 3. A leading `www.` does not count as a separate domain.
- Statutory rates need at least one tier-1 candidate that passes every check, otherwise a hard failure
  (`no_authoritative_source`, or the reason code of the first failing check).
- **Any two tier-1 candidates with different values are a hard failure** (`conflicting_official_sources`),
  regardless of effective date. A failing tier-1 candidate with the same value is excluded with a warning.
- Tier 2/3 agreement counts distinct domains (corroboration). A tier 2/3 value that differs from tier 1 is
  recorded as a disagreement with a warning; values are never averaged or voted on.
- Per-candidate checks: unit; bounds; the number appears in the excerpt (thousands separators and trailing
  zeros normalised; percent rates need %, "per cent" or "percent" right after the number; FX excerpts must name
  the currency); effective date (ISO, at most `max_effective_date_future_days` ahead). Excerpts are capped at
  2,000 characters when stored, and the check runs on the stored text.

### Versus the approved record

- Same value + newer effective date: reconfirmation proposal (lets `as_of` move forward).
- Same value + same or older date: no proposal (unchanged).
- Different value + older date: hard failure `older_than_current`.
- A change above `max_change_pct` is a failed check and a warning, not a rejection.
- With no approved baseline there is a warning, and the YAML placeholder value and change are shown as
  information only.

### Benchmarks

- `min_samples` counts valid samples before outlier removal. Each domain counts once (the median of its
  samples). Outliers outside 1.5 x IQR are removed; `min_distinct_domains` must still hold afterwards; the
  spread high/low must not exceed `max_spread_ratio`.
- **A benchmark never becomes one exact number.** `default_freight_inr` sets both default-freight entries (low
  and high) in one step, or neither; expected stays their midpoint and the median goes in the note. Clearing,
  port/CFS and domestic transport use value = median with `range_low`/`range_high` = low/high; the engine uses the
  range in the low/high scenarios only when both bounds are set.
- Benchmark entries carry the label "market benchmark, not an official figure" with sample and domain counts.
- The config rejects a lone range bound, a range that breaks `range_low <= value <= range_high`, and a range on
  any entry other than clearing, port/CFS, domestic transport and certification.

### Approval

- **CLI only** (`python -m app.decision.rates.review`); there is no HTTP endpoint. **The approver name is
  self-reported**; the MVP has no authentication.
- Warnings need `--acknowledge-warnings` and a non-empty `--note`. Only pending proposals no older than
  `proposal_expiry_days` can be approved, and the evidence hash is re-checked.
- A new pending proposal supersedes the older pending one for the same key.

### Store

- Append-only JSON lines under `app/decision/rates/data/` (ignored by its own `.gitignore`). Writes are atomic
  (temp file, then rename) and never edit earlier lines. A duplicate proposal ID is refused.
- A corrupt last line is skipped with a warning, and appends are refused until the file is repaired. A corrupt
  earlier line or contradictory events raise `StoreCorruptionError`. Review commands fail closed and the loader
  does not catch it. **Handling `StoreCorruptionError` is the caller's job:** the investigation flow must catch
  it, fall back to the YAML placeholders and show a visible warning.
- Single writer only; there is no file locking.

### Known limitation

- Agreement between websites is not proof of correctness. The reviewer must read the official excerpt; `show`
  prints it with that reminder.

### Open items

- Live TinyFish adapter; it should prefer the newest notification.
- Scheduler for refreshes.
- Notification to the reviewer when proposals are waiting.
- HS-code coverage beyond the Bluetooth speaker.
- Optional per-rate auto-apply for FX.
- Authentication for approvers.
- Confirming the tier-1 domain lists and filling the tier-2 lists.

### Additions (after review)

- **Fallback after a hash mismatch (accepted).** If the latest approval for a key is ignored because its evidence
  hash does not match, the previous valid approval is used. The entry note then says "latest approval ignored
  (evidence hash mismatch); using the approval from <date>", and the loader returns the same text as a warning.
- **Tier-1 domains and policy numbers are proposals.** The team confirms them in a browser. Tier-2 lists stay
  empty.
- **Fixture data.** `FixtureFetcher` marks every candidate as fixture data. A proposal built from it shows
  "FIXTURE DATA, NOT REAL EVIDENCE" in `show`, and `approve` refuses it unless `--allow-fixture` is given; the
  approval records that. The fixture flag is part of the evidence hash, and the loader marks such entries and
  warns about them.
- **Accepted deviations:** `cost_engine.py` lines rewritten for non-duty ranges; a lone range bound is rejected;
  a leading `www.` is not a separate domain; the builder's `UnchangedResult`; extra `CheckResult` fields.
