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

## 6. Verification — Part 1: normalisation rules (proposed, to confirm)

Code: `app/decision/verification_config.py`, `app/decision/verification_normalizers.py`. Values:
`app/decision/verification_config.yaml`.

**Registration number normalisation:**

- Strip case, spaces, hyphens and slashes.
- Compare the stripped strings exactly. No fuzzy matching.
- Example: "R-41234567", "r41234567" and "R 41 234 567" all normalise to "R41234567".

**Name normalisation (manufacturer, factory_location, brand, category):**

- Unicode NFKD normalisation, then encode as ASCII ignoring errors.
- Lowercase.
- Remove punctuation (keep only letters, digits and spaces).
- Remove legal suffixes from the configured list (whole-word match only, after splitting into
  tokens).
- Collapse whitespace and strip.
- Sort tokens alphabetically, so word-order differences don't produce a mismatch.
- Empty string after normalisation is treated as a missing value (unknown).

**Model normalisation and wildcard matching:**

- Same steps as name normalisation, except tokens are NOT sorted (model numbers are
  order-sensitive).
- Wildcard characters: `*` (zero or more characters), `?` (exactly one character), `x` or `X` at
  the end of a token (exactly one digit). Example: "BT-1xx" matches "BT-100" through "BT-199";
  "BT-1*" matches anything starting "BT-1"; "BT-1?" matches exactly "BT-10" through "BT-19".
- A scope entry is a wildcard pattern if it contains `*`, `?` or a trailing x/X token; otherwise
  it is an exact match after normalisation.
- Matching is case-insensitive on the normalised strings.

Note: wildcard patterns are data, not code. Never use `eval` or `exec`.

### Part 2: comparison and overall result

Code: `app/decision/verification_engine.py`.

**Reliable record.** A record is reliable only when `source_type == "official_portal"` AND
`excerpt` is non-empty AND `evidence_id` is present. Anything else is not reliable. On an
unreliable record (including `record is None`), every field result is `unknown`, never
`mismatch` — absence of evidence yields `unverified`, never `contradiction_detected`.

**Required fields:** `registration_no`, `manufacturer`, `model_scope`, `validity`.
**Optional fields:** `factory_location`, `category`, `brand`.

**A value missing on either side (claim or record) is `unknown` for that field** — this rule
is the same for every field, including `registration_no`: a claim with no registration number,
or a record with none, is `unknown`, not `mismatch`.

**Overall result (first match wins):**

1. Any `mismatch` on a required field, against a reliable record -> `contradiction_detected`.
2. Mismatch only on optional field(s) (no required mismatch) -> `unverified`, with the mismatched
   fields listed in `conflicts`.
3. Any required field `unknown` or `partial` -> `unverified`.
4. All required fields `match` and the record is currently valid -> `verified`.

**Validity.** Evaluated against the `as_of` date passed in by the caller, never the clock.
`as_of` after `valid_to`, `as_of` before `valid_from`, or `status` in `inactive_statuses` ->
validity `mismatch` (with a reliable record). `as_of == valid_from` and `as_of == valid_to` are
both inside the valid range. Missing `valid_from`, `valid_to` or `status` on a reliable record
-> validity `unknown`.

**Output wording.** Use "potential certification mismatch" and "could not verify". Never the
words "fraud" or "fake", anywhere in `reasoning` or `seller_request_list`.

**Seller request list.** One sentence per conflicting or unknown-required field, built only from
values already present on the claim. A field whose claim-side value is missing contributes no
sentence that names that field's value — never invent a value to ask about.

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

## 8. Rules, classification and risk (proposed, to confirm)

Code: `app/decision/rules/rule_engine.py`, `app/decision/classifier.py`, `app/decision/risk_engine.py`.
Data: `app/decision/rules/<category>_rules.yaml`, `app/decision/classifier_config.yaml`,
`app/decision/risk_weights.yaml`.

**All rule content requires human verification against official sources before the demo.** The rules file and
every rule carry that `content_status`, and each check's reasoning repeats it. Source links are portal home
pages only.

### Rule format

- One file per category, `<category>_rules.yaml`, with `category`, `rules_version`, `content_status` and `rules`.
  The category name must match `^[a-z][a-z0-9_]*$`, so it cannot point outside the rules folder. A category with
  no file has no rules (empty list).
- Each rule: `id`, `category`, `area`, `condition`, `result_if_true`, `requires_evidence`, `source_urls`,
  `version`, `effective_date`, `last_reviewed`, `mandatory` (default true), `prohibition` (default false),
  `content_status`. Unknown keys, duplicate ids, or a rule category that differs from the file are rejected.
  One bad rule rejects the whole file.
- `result_if_true` may only be `potentially_applicable`, `unverified` or `not_applicable`. A rule alone can never
  claim `verified` or `contradiction_detected`; those need evidence.
- All five Bluetooth speaker rules (import_policy, bis, wireless, battery, labelling) are **mandatory**.

### Condition format

- A condition is a structured dict, **never an expression string** (the PRD's `"category == '...'"` form is
  rejected).
- Leaf: exactly `{field, op, value}`. `field` is a lowercase name, optionally dotted for nested dicts
  (`a.b`). `op` is one of `eq`, `ne`, `in`, `not_in`, `gte`, `lte`, `contains`.
- Combinators, one key each: `{all: [...]}`, `{any: [...]}` (non-empty lists), `{not: {...}}`.
- Values are str, bool or int (lists of these for `in`/`not_in`; int only for `gte`/`lte`). Floats are rejected.
- Limits checked at load: depth at most 8, at most 64 nodes.

### Safe evaluator

- A hand-written recursive matcher walks the dict. No `eval`, `exec`, `compile` or attribute access; field
  lookup only reads dict keys.
- Three-valued: each node is true, false or unknown.
  - A leaf is unknown when the field is missing or `None`, or its type does not match the value (a bool never
    equals an int; a string never equals a number).
  - `all`: false if any child is false, else unknown if any child is unknown, else true. `any` mirrors it.
    `not` keeps unknown as unknown.
- Status from the condition:
  - false -> `not_applicable`.
  - unknown -> `unverified`, naming the missing facts. **A missing fact never yields `not_applicable`.**
  - true -> evidence decides: any required evidence `contradiction_detected` -> `contradiction_detected`; all
    required evidence `verified` -> `verified`; otherwise `result_if_true`. Evidence that is present but
    `unverified` does not change the status (it is named in the reasoning).
- Evidence is a mapping of evidence type (for example `registration_record`) to `{evidence_id, status}`, where
  status is `verified`, `unverified` or `contradiction_detected`. The evidence producer (for example the
  verification engine) is responsible for reliability.
- `prohibition_applies` is true only when a `prohibition: true` rule's condition is true.
- Each `RequirementCheck` carries `rule_id`, `rule_version`, `area`, `status`, `reasoning`, `evidence_ids`,
  `mandatory`, `prohibition_applies` and `requires_evidence`.

### Classification

- Keyword and attribute matching only, on lowercased, accent-folded, punctuation-stripped text; whole words or
  phrases only.
- A category is considered only if one of its anchor keywords appears. No anchor for any category ->
  `unsupported`.
- Score = sum of matched signal weights (Decimal, capped at 1). Score at or above `confidence_threshold` (0.6) ->
  `confirmed` (confidence high at or above `high_confidence_threshold`, else medium); below -> `needs_confirmation`,
  confidence low. A tie between categories -> `needs_confirmation`.
- HS codes are suggestions marked "suggested, not verified", never a classification.

### Risk engine interpretations

- Only mandatory checks are scored and count for precedence rules 3 and 4.
- The identity result is scored with the same weights as a check (`verified` 0, `unverified` 2,
  `contradiction_detected` 3) and counts as a mandatory check. A missing identity result counts as `unverified`.
- Precedence rule 2 (`insufficient_information`) also fires when quantity or purpose is `None` (treated as a
  skipped key fact) or when no mandatory check was evaluated. Its risk level follows the score, with a
  contradiction still forcing high.
- A prohibition takes precedence over everything, including missing classification.
- `likely_importable` is always risk `low` (section 2 rule 5), even when bonuses make the score above 1; the score
  is still reported.
- The cost estimate never changes the score; it only adds a next action when its rates are unverified or stale.
- `RiskResult` also carries `evidence_ids` and `rule_versions` (`rule_id@version`).

### Note on the worked demo

The section 3 score of 7 is a **risk-engine input example** (BIS and wireless checks only), not a full five-rule
run. Running all five mandatory Bluetooth speaker rules on the demo product gives five `potentially_applicable`
checks, so the score is 10 (still `conditional_import`, high).

### Approved interpretations

- Missing identity result: counts as `unverified`, adds 2 to the score. Approved.
- No mandatory checks evaluated: outcome is `insufficient_information`, not `likely_importable`. Approved.
- `likely_importable` is always low risk, even when bonuses push the score above 1. Approved.
- All three are confirmed by tests: `test_missing_identity_result_counts_as_unverified`,
  `test_no_mandatory_checks_is_insufficient_information`, `test_likely_importable_is_low_even_with_bonuses`.
- Still to confirm before demo: rule content and source URLs.

## 9. Report schema (frontend contract)

Code: `app/decision/report_schema.py` (models), `app/decision/report_builder.py` (`assemble_report`).

**The report models are the contract with the frontend.** Changing a field name, type or meaning is a contract
change and needs a matching frontend change.

### Shape

- Follows PRD B5 with these differences:
  - JSON keys are camelCase (`riskLevel`, `evidenceIds`, `sellerClaims`); Python fields are snake_case.
    Serialise with `FullReport.to_frontend()` (or `model_dump(by_alias=True)`). No snake_case key appears in
    the JSON.
  - Enum values stay lowercase (section 1), for example `conditional_import`, not `CONDITIONAL_IMPORT`.
  - Money and rates are Decimal and serialise as strings (`"1542.88"`), never floats.
  - Extra fields beyond B5: `score`, `reasons`, `nextActions` (numbered, 1 = most urgent; `nextAction` is the
    first one's text), `ruleVersions` (`rule_id@version`), `questionsSkipped`. The summary classification also
    carries `confidence` and `candidateHsCodes` (suggestions only).
- Every model rejects unknown fields. Only existing enums are used; evidence `sourceType` is one of `listing`,
  `official_portal`, `user_upload`, `rule_source`.
- `disclaimer` is always exactly "Decision support only. Not legal clearance or customs approval." Any other
  value is rejected.
- No `generated_at`: the builder never reads the clock. The caller adds a timestamp when it stores the report.

### Validation

- **Evidence integrity:** every evidence ID referenced by a profile fact, a check or the certification
  comparison must appear in `evidence`. A dangling ID or a duplicate evidence ID is a hard validation error.
- Profile facts sit in the list matching their `kind` (`confirmed`, `seller_claim`, `user_supplied`). Confirmed
  facts need an `evidence_id`. Fact values are str, int, bool or Decimal; floats are rejected.
- Evidence `retrievedAt` must be timezone-aware.

### Assembly

- `assemble_report(investigation_id, classification, checks, identity_result, cost_estimate, profile, evidence,
  questions_skipped)` calls `compute_risk` with the default risk config.
- **Quantity and purpose are read from the profile's `user_supplied` facts** (`quantity` as int, `purpose` as
  str). A wrong type is an error. A missing fact, or a field listed in `questions_skipped`, is passed to
  `compute_risk` as `None`, so the outcome is `insufficient_information` (section 8). A skipped `category` drops
  the classification.
- `identity_result` is the verification engine's `VerificationResult` (or `None`); its overall result is scored and
  the full result becomes `certificationComparison`. `None` gives a null comparison and is scored as unverified.
- `summary.bis` and `summary.wireless` are the status of the first check in that area, or null.
- `summary.sellerClaimsBis` is true when a seller-claim fact `bis_registration_no` or `certification_claims` has
  a non-empty value (or `true`).
- `summary.illustrativeCostPerUnit` is the expected per-unit cost; `cost` is null when no estimate was made.

### Demo

The 100-speaker demo (five rules, identity unverified, resale, quantity 100, needs_confirmation, golden cost
inputs) gives `conditional_import`, high, score 10, expected cost per unit 1542.88 INR.

## 10. Storage (proposed, to confirm)

Code: `app/db/` (`database.py`, `migrations.py`, `repositories.py`, `session.py`, `ids.py`). **The schema is in
`app/db/migrations.py`.**

### Decisions

- **Supabase Postgres replaces SQLite.** SQLite was the MVP plan; Supabase is used for persistence across
  deploys. The code talks to it with `asyncpg` directly (no Supabase client), through `DATABASE_URL`.
- **Pool:** minimum 1, maximum 5 connections. The Supabase project is on Nano compute with 15 connections in
  total, so this leaves headroom for migrations, local development and Supabase's own internal connections.
  `statement_cache_size=0`, so it also works behind Supabase's
  transaction pooler. SSL comes from the connection string (`sslmode=require`).
- **Credentials never reach logs.** The connection string is never logged or put in an error message; logs and
  errors name only the host. A failed connection raises an error that drops the original exception.
- **All IDs are ULIDs** (investigations, sessions, facts, evidence, questions, snapshots), stored as TEXT. The
  repositories reject any other ID before running a query. Demo fixture IDs such as `ev_listing_1` are test-only.
- **Money is TEXT** holding a Decimal string (`"1542.88"`). Floats are rejected, and the JSONB codec rejects a
  float anywhere in a JSON value and reads fractional numbers back as Decimal.
- **Timestamps come from the caller** (`created_at`, `expires_at`, `deleted_at`, ...) and must be
  timezone-aware. There is no hardcoded retention period.
- **Soft delete for investigations:** `soft_delete` sets `deleted_at`. A soft-deleted investigation, and every
  fact, evidence item, question, report and cost estimate under it, is never returned by any reader.
- **Hard delete removes all evidence:** `hard_delete` deletes the investigation row, and every child table
  (`order_inputs`, `facts`, `evidence`, `questions`, `reports`, `cost_estimates`, `raw_snapshots`) cascades. It
  works on soft-deleted rows too.

### Schema (differences from PRD B4)

- Tables as listed in `migrations.py`. `requirement_checks`, `certification_comparisons` and `rule_sets` are not
  separate tables.
- `reports.report_json` (nullable JSONB) holds the full `FullReport.to_frontend()` snapshot (section 9);
  `outcome`, `risk_level`, `score`, `next_actions` and `rule_set_versions` are kept as columns too.
- `order_inputs.investigation_id` is the primary key (one row per investigation).
- Row Level Security is enabled on every table with no policies, so Supabase's REST API (anon key) cannot read
  them. The direct Postgres role this app uses bypasses RLS.
- Indexes: `investigations.session_id` (live rows only) and `investigation_id` on `facts`, `evidence`,
  `questions` and `raw_snapshots`.
- Columns are nullable as in the specification; required values are checked in the repository layer.
- Question `status` is `open`, `answered` or `skipped` (proposed).
- Fact values are stored as text (a bool becomes `true` or `false`), so the original type is not preserved.

### Sessions

- The session ID is a ULID in a cookie `importsafe_session`, signed as `<ULID>.<hex HMAC-SHA256>` with
  `SECRET_KEY` (at least 32 characters, no default). A missing, malformed or tampered cookie is replaced with a
  new ULID. Cookie attributes: HttpOnly, SameSite=Lax, Secure, path `/`.
- `get_investigation` can take a `session_id` so a session only sees its own investigations.

### Not done here

- Wiring the pool into the FastAPI startup and shutdown, and setting the cookie in a route (`main.py` and the
  routes are out of scope for this step).
- Database tests need `DATABASE_URL`; they run in a throwaway schema `test_<16 hex>` that is dropped afterwards,
  and skip when it is not set.

## 11. TinyFish connector (proposed, to confirm)

Code: `app/services/tinyfish/` (`connector.py`, `models.py`, `goals.py`, `live_adapter.py`, `fixture_adapter.py`,
`evidence_capture.py`). `client.py` is the legacy blocking client, kept for the P1/P2 route only.

### Decisions

- **Interface.** `TinyFishConnector` (a `Protocol`) has two async methods: `extract_listing(url)` (Task A) and
  `fetch_registry_record(registration_no, manufacturer, model)` (Task B). Results are `ExtractionResult` and
  `RegistryResult` (adds `record_found`). Both carry `is_fixture`.
- **Never raises.** A missing key, HTTP error, bad response, timeout or a run that is not COMPLETED gives a result
  with `failed=True` and a status (`TIMEOUT`, `NOT_CONFIGURED`, `ERROR`, `HTTP_<code>`, `FAILED`, `CANCELLED`,
  `PAGE_UNAVAILABLE`). A FAILED run keeps whatever fields it returned (partial result).
- **Live flow.** `POST /v1/automation/run-async` (body `{url, goal}`, header `X-API-Key`), then `GET /v1/runs/{run_id}`
  every 3 seconds until COMPLETED, FAILED or CANCELLED, or 90 seconds in total.
- **Untrusted text.** Page text and every extracted value are stripped of control, zero-width and bidi characters and
  capped (excerpts 2,000 characters, values 2,000, raw text 20,000). `raw_text` is wrapped in
  `<<<UNTRUSTED_PAGE_TEXT_START>>>` / `<<<UNTRUSTED_PAGE_TEXT_END>>>`, and any copy of those markers inside the text
  is removed. Only whitelisted keys (`LISTING_KEYS`, `REGISTRY_KEYS`) are kept; extra keys are dropped; values are
  reduced to str, int, bool, list or dict; floats become text. Search terms put into the Task B goal are filtered.
  Logs carry only run ID, status and field counts, never page content or values.
- **Missing values.** The goals ask for `N/A` rather than a guess. `N/A`, null and empty values are left out of
  `fields`. A listing with no extracted fields counts as failed; a registry lookup with no record is not a failure
  (`record_found=False`).
- **Excerpts.** The agent returns `{"value", "excerpt"}` per key. `evidence_capture` makes one `EvidenceItem` per
  field with a non-empty excerpt (`listing` for Task A, `official_portal` for Task B), with a ULID ID. Fields with no
  excerpt stay low confidence (B6) and produce no evidence. `build_evidence_pairs` returns `(field, EvidenceItem)` so
  callers can link facts to evidence.
- **Fixtures.** `FixtureTinyFishConnector` answers the `demo.py` listing URL (headphones, values from
  `DEMO_RAW_RESULT`), the BT-100 speaker URL (values from `tests/fixtures/demo_report_inputs.py`) and registration
  number R-41234567 (matched after normalisation). Results have `is_fixture=True` and every excerpt starts with
  `[FIXTURE DATA]`. Anything else falls back to the live connector. The BT-100 price and currency come from the
  golden cost inputs and have no excerpt.
- **Registry portal.** Task B needs a page to search. The default is `https://www.crsbis.in/BIS/` (settable on the
  connector). **Unverified.** The fixture record uses `registry.example`.

### Endpoint check (docs.tinyfish.ai)

- Confirmed: `POST /v1/automation/run-async` starts a run and returns `run_id`; `GET /v1/runs/{id}` returns the run
  object with `status` (PENDING, RUNNING, COMPLETED, FAILED, CANCELLED), `result`, `error` and `num_of_steps`
  (null while in progress); auth is `X-API-Key`; `POST /v1/runs/{id}/cancel` exists.
- Not confirmed: the exact JSON the agent returns for our goals (the shape in `goals.py` is our request, and the
  parser tolerates a bare value without an excerpt); the registry portal URL; real-site behaviour (no live call has
  been made in this step).
- No change from the spec was needed.

### Open items

- **Cancel on timeout.** The connector does not cancel a timed-out run; it expires on TinyFish's side. Cancelling
  (`POST /v1/runs/{id}/cancel`) would save TinyFish credits.
- Confirm the registry portal URL and run a live check of both tasks.
- The investigation coordinator should turn a failed result into a `NEEDS_INPUT` stage and a follow-up question.
- A fixture result must never be presented as real evidence; the coordinator should surface `is_fixture`.
