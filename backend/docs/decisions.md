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
