---
spec: "OBS-007-cert-expiry-alerting"
verdict: "PASS WITH GAPS"
reviewed_sha: "8b62b208aafacd2d104ba5a78cebc37aeb727889"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-10"
---
## Adversarial review

**Scope**: OBS-007-cert-expiry-alerting
**Sources**: `specs/OBS-007-cert-expiry-alerting/{proposal,tasks,verification}.md`, `infra/k8s/base/services/grafana-alerting/`, `infra/k8s/overlays/prod/services/grafana-alerting/`, `toolkit/features/alert_smoke.py`, `tests/test_alert_smoke.py`, `tests/test_grafana_alerting_render.py`, `docs/runbooks/acme-alerting.md`

### Spec and task alignment
- All 6 Acceptance Criteria are met.
- The `for: 5m` interval logic was explicitly accepted in the previous review round. The comment correctly reflects reality.
- `noDataState: OK` correctly clears the rule when Traefik stops reporting errors or is unavailable, which is the exact intended behavior.
- The verification tests and runbook accurately reflect the operational characteristics of the alert.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | THEORETICAL | tests | Flaky log counting in `alert_smoke.py` due to sliding window | `count_deliveries` uses `kubectl logs ... --tail=300` and compares absolute counts (`deliveries() > baseline`). If Apprise logs enough lines during the wait, an old delivery falls out of the tail, causing the absolute count to decrease or stay flat even when a new delivery occurs. This can mask successful deliveries and cause false test failures. | `tests/test_alert_smoke.py::TestTeardownAlwaysRuns::test_reports_each_stage_separately` | tests |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | Alert fires appropriately and clears appropriately; edge cases (like ANSI codes) are handled gracefully. |
| Verification       | B | Reproducible verification commands exist, but the smoke test relies on a brittle sliding window count. |
| Scope              | A | Diff matches proposal exactly; no scope creep. |
| Reliability        | A | Fails closed (`execErrState: Error`), recovers gracefully (`noDataState: OK`). |
| Maintainability    | A | High quality code with Cyclomatic Complexity < 10, explicit and clear comments on Grafana workarounds. |
| Handoff-readiness  | A | Comprehensive runbook created with exact commands and expected behaviors. |

### Verdict
PASS WITH GAPS

### Recommended next steps
- Address the `alert_smoke.py` sliding window count to use `--since-time` (or stream) rather than `--tail=300` to prevent theoretical flakes on noisy Apprise pods.
- Run `dotf spec archive` or `/spec archive`. The current state satisfies the definition of done and the gaps are non-blocking.
