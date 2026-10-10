---
spec: "TOOL-062-gitea-actions-secrets"
verdict: "FAIL"
reviewed_sha: "03a708276e4abaaefc7dd86df6b75f49257f91d0"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-10"
---

## Adversarial review

**Scope**: TOOL-062-gitea-actions-secrets
**Sources**: `specs/TOOL-062-gitea-actions-secrets/{proposal.md,tasks.md,verification.md,features.json}` and `git diff d99581349a251d3d9a05071d899240252642bee3...HEAD`

### Spec and task alignment
- All acceptance criteria are mapped to tests and features.json entries.
- The behavior mostly aligns with the spec, but there is a gap in checking undeclared secrets on unmanaged repositories, and a redaction flaw.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Blocker  | THEORETICAL | security | Secret leak in report: A Gitea error containing a JSON-escaped secret (e.g. `\n`) bypasses `str(exc).replace(value, "<redacted>")`, leaking the secret. | `str(exc)` will contain the escaped characters (`\\n`), so `value` (un-escaped) won't match literal strings with special characters. | `test_a_forge_error_that_echoes_the_value_is_redacted_in_the_report` | code |
| Major    | REAL    | correctness | The CLI loop `for repo in sorted({t.repo for t in targets})` only fetches live secrets for repositories with at least one declared secret. Undeclared secrets on completely unmanaged repositories are silently ignored, violating AC5. | CLI loop restricts fetch to `targets` repos; the test mocks a state (`targets=()`, `live={RESUME...}`) that the CLI loop can never reach. | `test_an_undeclared_live_secret_is_reported_and_never_removed` | code + spec |
| Minor    | REAL    | tests | `test_a_forge_error_that_echoes_the_value_is_redacted_in_the_report` uses `in repr(report)` which double-escapes strings. A leak of `\n` would evade the `in` check, falsely passing. | `value!r` and `repr(report)` interactions hide mismatched escapes. | `test_a_forge_error_that_echoes_the_value_is_redacted_in_the_report` | tests |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Most criteria met, but misses undeclared secrets on unmanaged repos. |
| Verification       | B | Evidence present for all criteria, but redaction test has a false positive. |
| Scope              | A | Diff matches proposal exactly; no scope creep. |
| Reliability        | C | Redaction logic fails to scrub JSON-escaped secrets from error messages. |
| Maintainability    | A | Clear naming, small functions, well-documented logic. |
| Handoff-readiness  | A | Spec updates included and complete. |

### Verdict
FAIL

### Recommended next steps
- **code**: Fix secret redaction in `execute_actions_secrets` to handle JSON-escaped values in Gitea's error response (e.g., using regex or un-escaping the error before replacement).
- **tests**: Update `test_a_forge_error_that_echoes_the_value_is_redacted_in_the_report` to test a value with special characters (like `\n`) and avoid checking `in repr(report)` which double-escapes strings and creates a false positive.
- **code/spec**: Address the AC5 gap where undeclared secrets on unmanaged repos are ignored. If avoiding N requests to the forge is intentional, declare this scope limitation explicitly in `proposal.md` and `features.json`.
- **tests**: Update `test_an_undeclared_live_secret_is_reported_and_never_removed` to reflect reachable CLI state, or expand the CLI loop to fetch all repos if AC5 applies globally.
