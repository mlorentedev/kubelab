---
spec: "OBS-007-cert-expiry-alerting"
verdict: "FAIL"
reviewed_sha: "4a7d5e96cf554cd02ffd8dcd752c3453788659ef"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-10"
---

## Adversarial review

**Scope**: OBS-007-cert-expiry-alerting
**Sources**: `specs/OBS-007-cert-expiry-alerting/{proposal,tasks,verification}.md`, `git diff 6d3d9246d16d4c0d4244d1da2c697e2bfeadc32f...HEAD`

### Spec and task alignment
- Implementation correctly provisions the alert rule and Apprise contact points using ConfigMap hashing to ensure changes trigger a rollout.
- The base/overlay model for contact points correctly scopes staging (`log` tier) versus production (`page` tier) using a minimal patch footprint (`receiver` override on the root policy).
- An explicit decision was made to not wait for a live renewal failure, and instead an automated smoke test (`make alert-smoke`) applies an unissuable domain IngressRoute to verify the end-to-end alert state changes.
- AC3 was verified once by measurement and relies on a ticket (#2195) for automated coverage, which is documented and acceptable.
- `noDataState: OK` is correctly used to handle empty vectors resulting from the Loki query.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Blocker  | THEORETICAL | Reliability | The alert logic fires on transient errors, contradicting the stated intent. A `count_over_time(...[10m])` at a `5m` interval means a single failure log line stays in the window for at least two evaluations, mathematically satisfying `for: 5m`. A transient failure that succeeds on retry will still page the operator. | Code inspection: The `[10m]` window guarantees single-event persistence across consecutive `5m` evaluations, directly opposing the comment "a rule that pages on the first blip trains people to ignore it". | UNTESTED | code + tests (add a test case that ensures a single transient failure does not page) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | D | The alert logic fires on transient errors, fundamentally failing to solve the alert fatigue problem it specifically set out to avoid. |
| Verification       | A | `make alert-smoke` and render tests prove the vast majority of criteria, properly asserting on outputs rather than assumptions. |
| Scope              | A | Diff matches proposal precisely with no significant scope creep. |
| Reliability        | B | `noDataState: OK` and configuration rollout mechanisms are solid, but the false positive logic gap weakens the reliability of the alert signal. |
| Maintainability    | A | The use of kustomize base/overlays for alerting and python scripts for smoke tests is clean, robust, and well-structured. |
| Handoff-readiness  | A | Verification artifacts filled, tests pass, and `acme-alerting` runbook accurately added. |

### Verdict
FAIL

### Recommended next steps
- Update the alert rule query window from `[10m]` to `[5m]` so that `for: 5m` requires failures in two consecutive windows (i.e., a failure that actually persists for 5+ minutes).
- Add a test case to `toolkit/features/alert_smoke.py` (or related test suite) that verifies a single failure event (followed by success) does *not* fire the alert.
- Run `dotf spec archive` once the rule logic is fixed and the review is PASS.
