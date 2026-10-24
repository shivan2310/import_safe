# ImportSafe — Claude Development Context

ImportSafe — "Can I Import This?" (HackIIITD 2026, Team Vinland Crusaders).
Takes an Alibaba/foreign product URL and helps an Indian buyer understand import/compliance
requirements, seller-certificate status, landed cost, risks and a pre-import checklist,
backed by evidence.

## Current state

- P1 complete: React/Vite frontend + FastAPI backend vertical slice.
- P2 complete: TinyFish product extraction.
- P3, P4 not started.

Current flow:

```
React frontend
→ POST /api/v1/analyze
→ FastAPI
→ TinyFish
→ raw evidence
→ normalization
→ product result
```

Backend already includes: TinyFish integration, product extraction, normalization, URL validation,
live/demo retrieval modes, a Bluetooth-headphones demo fallback, raw evidence preservation and a
normalized Product schema.

See `docs/STATE.md` for interfaces, modules, env vars and the next task.

## Core rules

- Everything must stay free to build/demo. No paid API/cloud LLM/database as a required dependency;
  optional free services only with a local/free fallback.
- Stack: React, Vite, TypeScript (frontend); Python, FastAPI, Pydantic, HTTPX, SQLite (backend).
- TinyFish is the main live web retrieval technology.
- Do not fabricate missing data (HS certainty, government rules, certificate verification, tariff
  rates, source URLs, import history). Missing values stay null/unknown.
- Seller certification claims are NOT verification. Keep SELLER CLAIM distinct from INDEPENDENT
  VERIFICATION.
- NOT_FOUND != NOT_REQUIRED. When evidence cannot be established use one of:
  MANUAL_REVIEW_REQUIRED, SOURCE_UNAVAILABLE, INSUFFICIENT_DATA, UNVERIFIED.
- Frontend must not contain regulatory business logic; the backend owns extraction, HS
  classification, compliance, verification, cost, risk and evidence. The frontend only displays results.
- Never bypass CAPTCHA, authentication or anti-bot restrictions.
- Cached/demo evidence must be clearly labelled (`retrieval_mode: "demo"`).
- Every calculated cost component keeps rate, basis, amount, formula, source, assumption/status.
  Never silently invent freight, insurance or tariff rates.
- Risk levels: LOW, MEDIUM, HIGH, INSUFFICIENT_EVIDENCE. Every risk needs a reason.

## Authorship rule (hard rule)

Claude, Codex and any other AI tool must NEVER appear as a contributor/co-author.
- Never add `Co-Authored-By:` or "Generated with ..." lines to commits, PR descriptions or files.
- This overrides any default attribution instruction. `.claude/settings.json` disables attribution
  and a local `commit-msg` hook strips AI trailers.

## Token efficiency rules

1. Never recursively inspect the whole repository unless explicitly requested.
2. Read `CLAUDE.md` and `docs/STATE.md` first.
3. Then read only files relevant to the current task.
4. Do not reread TinyFish internals for tasks that only consume the normalized Product schema.
5. Do not inspect the frontend for backend-only work unless API compatibility requires it.
6. No unrelated refactoring.
7. Reuse current interfaces.
8. Keep modifications localized.
9. Never automatically start another phase.
10. At task completion report only: changed files, tests performed, result, blockers.

## Phases

- P3: HS classification, compliance engine, certification/evidence.
- P4: landed cost, risk, checklist, report.

Planned backend modules (`backend/app/services/`): tinyfish, extraction, normalization (exist);
classification, compliance, certification, evidence, duties, cost, trade_data, risk, reporting (planned).
