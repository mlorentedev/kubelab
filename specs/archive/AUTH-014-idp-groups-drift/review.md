---
spec: "AUTH-014-idp-groups-drift"
verdict: "PASS WITH GAPS"
reviewed_sha: "f2b3b6db569d13769aa7f4818d7aef71c1122372"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-09-29"
---

## Adversarial review

**Scope**: AUTH-014-idp-groups-drift
**Sources**: `specs/AUTH-014-idp-groups-drift/{proposal,tasks,verification}.md`, `features.json`, and git diff `98e00add2cb4d85a68950c7405841b708d8f5626...HEAD`

### Spec and task alignment
- `tasks.md` Implementation section is completely checked, but the Closing section remains entirely unchecked despite the implementation being ready for archive.
- `verification.md` claims `mypy` is clean, but a type annotation error is present in the modified test file.
- The previous review's cyclomatic complexity gaps have been correctly addressed (`reconcile` is now exactly at the threshold of 15).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | test-typing | `mypy` check fails on `tests/test_access_review.py:129`, contradicting the `verification.md` claim that it is clean. | `.venv/bin/mypy toolkit/features/access_review.py tests/test_access_review.py` outputs `error: Need type annotation for "doc" [var-annotated]` | UNTESTED | tests |
| Minor | REAL | process | The "Closing" section checkboxes in `tasks.md` are unchecked despite implementation and verification being completed. | Code read of `specs/AUTH-014-idp-groups-drift/tasks.md` | UNTESTED | spec |
| Minor | SPECULATIVE | security | If a password hash is maliciously or accidentally placed as a dictionary key (username) in the live Secret, it would be echoed in the finding's `user` field. | Code read of `_groups_by_user` where keys are treated as safe usernames. | UNTESTED | — (surface only; do not gate) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | A | All acceptance criteria met perfectly; drift logic is sound and resilient to empty/absent data. |
| Verification | A | `features.json` verifications are fully reproducible and correctly map to ACs. |
| Scope | A | Diff strictly implements the proposed IDP drift checks; no scope creep observed. |
| Reliability | A | Errors properly fail the review rather than crash; timeouts prevent hanging on unreachable spoke. |
| Maintainability | B | `reconcile` sits exactly at the Cyclomatic Complexity limit of 15; minor mypy error in test suite. |
| Handoff-readiness | B | Spec artifacts are well-documented, but the closing checklist in `tasks.md` was forgotten. |

### Verdict
PASS WITH GAPS

### Recommended next steps
- Address the `mypy` type annotation error in `tests/test_access_review.py:129` (tests set, can be edited freely).
- Note for the implementer: The closing checkboxes in `tasks.md` were left unticked. Since `tasks.md` is part of the contract set, do not edit it now as it would invalidate this review's SHA match. Disposition this gap in `verification.md` instead.
- `dotf spec archive` / `/spec archive` is **advisable** in the current state once the gaps are dispositioned in `verification.md`.
