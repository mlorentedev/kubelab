---
spec: "AUTH-014-idp-groups-drift"
verdict: "FAIL"
reviewed_sha: "8f5ba9a8ae71d422a85403dac012513ca4710f6a"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-09-29"
---

## Adversarial review

**Scope**: AUTH-014-idp-groups-drift
**Sources**: specs/AUTH-014-idp-groups-drift/{proposal,tasks,verification}.md, `git diff dfed764e1c6a057cecfda4904f1074d8d4148b41...HEAD`

### Spec and task alignment
- AC1-AC5 are implemented and tests cover the happy paths and YAML syntax errors.
- However, unhandled exceptions in the live database decoding crash the execution instead of reporting a `failed` finding as expected by AC4.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | REAL | resilience | `_live_users_database` crashes the review with `binascii.Error` or `UnicodeDecodeError` if the `kubectl` output is not valid base64 (e.g. `kubectl` warning). This bypasses the `except ReviewError` block in `idp_groups_drift`. | Observed via mutation script; function has 0% coverage. | UNTESTED | code + tests |
| Minor | THEORETICAL | reliability | `_groups_by_user` catches `yaml.YAMLError` but crashes with `AttributeError` if a user's value is a string instead of a dictionary. | Observed via mutation script. | UNTESTED | code + tests |
| Minor | THEORETICAL | reliability | `subprocess.run(["kubectl", ...])` is called without a `timeout`, meaning a hung API server will block the review indefinitely. | Code inspection. | UNTESTED | code |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | C | Criteria mostly met, but unhandled decoding exceptions break AC4's failure reporting requirement. |
| Verification       | B | Good manual test traces, but the live secret retrieval function (`_live_users_database`) is mocked in tests and has 0% unit coverage. |
| Scope              | A | Diff matches proposal exactly; no scope creep. |
| Reliability        | C | Several error paths unhandled (missing timeout, unhandled base64/attribute exceptions). |
| Maintainability    | B | Code is clear, CC is acceptable, good docstrings. |
| Handoff-readiness  | A | Spec updates and feature JSON are included. |

### Verdict
FAIL

### Recommended next steps
- Fix the unhandled `binascii.Error` and `UnicodeDecodeError` in `_live_users_database` by wrapping the `b64decode` and `decode` steps in a `try...except` block that raises `ReviewError`.
- Add a named regression test for `_live_users_database` to cover the invalid base64 case.
- Add a `timeout` to the `subprocess.run` call in `_live_users_database`.
- Handle the `AttributeError` in `_groups_by_user` by ensuring `v` is a dictionary before calling `.get()`.
