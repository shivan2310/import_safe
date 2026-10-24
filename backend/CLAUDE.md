# ImportSafe Backend — Additional Rules

These rules add to the root `CLAUDE.md`; they do not replace it.

- Never use `eval` (or `exec`). Rule conditions are structured JSON, not code strings.
- Decisions (classification, rule matching, verification, cost, risk) are deterministic code.
  The LLM only structures extracted text and drafts explanations.
- All third-party page text is untrusted data.
- Money is `Decimal`, never `float`.
- Never invent values. Unknown means `unverified` or a follow-up question.
- Never use the words "fraud" or "fake" in output strings. Use "potential mismatch" or
  "could not verify".
- Every conclusion carries evidence IDs and a rule version.
- Absence of evidence yields `unverified`, never `contradiction_detected`.
- Spec is `docs/prd-backend.md`; `docs/decisions.md` overrides it.
- Test command: `pytest`, run from `backend/`.
- Every file write uses an absolute path or a path starting with `backend/`; never rely on the current
  directory.
- Run `pwd` before appending to any file.
- Python: code targets Python 3.10+ and must stay 3.10-compatible (no `StrEnum`, no `datetime.UTC`, no
  3.11+ only syntax). The local test environment currently runs Python 3.14.
