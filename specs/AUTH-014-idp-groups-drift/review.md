---
spec: "AUTH-014-idp-groups-drift"
verdict: "PASS WITH GAPS"
reviewed_sha: "115d76681768d3367ce5f49e233cbeec592897b8"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-09-29"
---

## Adversarial review

**Scope**: AUTH-014-idp-groups-drift
**Sources**: specs/AUTH-014-idp-groups-drift/{proposal,tasks,verification}.md, `git diff dfed764e1c6a057cecfda4904f1074d8d4148b41...HEAD`

### Spec and task alignment
- All acceptance criteria are thoroughly met and proven via test artifacts and the live environment check.
- The implementer correctly addressed all prior review feedback by introducing a `timeout` bound to `kubectl`, gracefully catching base64 / unicode decoding exceptions (`ValueError`), and properly verifying type structures (`isinstance`) in parsed YAML prior to traversal.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | maintainability | The `reconcile` and `review_env` functions have a cyclomatic complexity of 23 and 17 respectively, which exceeds the acceptable limit (≤15) for B grade maintainability. | Observed via `radon cc toolkit/features/access_review.py`. | UNTESTED | code |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All acceptance criteria verified, negative paths covered, and password hashes strictly isolated from output. |
| Verification       | A | Excellent traceability in `features.json` and named `pytest` cases perfectly covering all newly defined behaviors. |
| Scope              | A | Diff matches proposal exactly; no scope creep. |
| Reliability        | A | Strong error handling including Kubernetes read timeouts, base64 validation, string coercion, and suppressed `yaml.YAMLError` chaining to avoid leaking secret contents. |
| Maintainability    | C | `reconcile` (CC 23) and `review_env` (CC 17) exhibit high cyclomatic complexity, primarily driven by conditional list comprehensions handling `stale` logic. |
| Handoff-readiness  | A | Spec updates included, and ADR/lesson generated (`lesson-484`). |

### Verdict
PASS WITH GAPS

### Recommended next steps
- [code] Consider refactoring `reconcile` or `review_env` to extract sub-routines (like the extraction of `editable` bindings or applying updates) in a future iteration to reduce cyclomatic complexity under 15.
