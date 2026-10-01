---
spec: "BACKUP-070-restore-window"
verdict: "PASS WITH GAPS"
reviewed_sha: "ad47aa4fc8b630bb3dc54ed993893353980b805c"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-01"
---
## Adversarial review

**Scope**: BACKUP-070-restore-window
**Sources**: specs/BACKUP-070-restore-window/{proposal,tasks,verification}.md, diff `d7d588611dd5079bcc07cf8bfa30b23ec7eae31e...HEAD`

### Spec and task alignment
- **AC1, AC2, AC3, AC4, AC5, AC6** are met. Code patches sync policies using `resourceVersion`, respects conflict, and safely manipulates auto-sync.
- The change fully addresses the root issue without introducing unacceptable complexity. Tests cover the expected behavior and handle conflicts explicitly.
- The use of JSON merge patches with RFC 7386 semantics correctly removes or updates specific sub-fields without overwriting the entire sync policy.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | logic | `_blocking_pods` ignores `matchExpressions`. If a Deployment's selector only uses `matchExpressions`, `matchLabels` is absent, so `labels` defaults to `{}`. `all(...)` then evaluates to `True` for every pod in the namespace, causing the open command to time out waiting for unrelated pods to terminate. | `labels = spec["spec"]["selector"].get("matchLabels") or {}` in `open_window()`, and `if all(...)` in `_blocking_pods()`. `grep` shows all current apps use `matchLabels`, making it theoretical for now. | UNTESTED | code + tests |
| Major | THEORETICAL | logic | `close_window` times out if the git-declared replicas for the Deployment is 0. The wait loop requires `want > 0`, which was added to wait out Argo CD's initial `replicas: 0` live state before sync completes. If git actually declares `replicas: 0` (e.g. permanently disabled), `want` correctly becomes 0, but the loop never exits. | `if sync == "Synced" and health == "Healthy" and want > 0 and ready == want:` in `close_window()`. | UNTESTED | code + tests |
| Minor | THEORETICAL | resilience | If the `kubectl scale` operation fails in `open_window`, it correctly raises a `WindowError` but leaves the Application paused with the holder annotation attached. This forces the operator to manually run `END=1` to restore state, which could be confusing if they haven't successfully scaled down. | `rc, _, err = run(_kubectl(spoke_kubeconfig, APP_NAMESPACE, "scale", ...))` happens after `_patch_application()`. If it fails, `raise WindowError(...)` leaves the app paused. | UNTESTED | code |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | Handled happy paths well, but failed to account for `matchExpressions` and `replicas: 0` configurations. |
| Verification       | A | Robust mutation testing and live staging execution provided as evidence. |
| Scope              | A | Strictly adhered to the proposal. |
| Reliability        | B | Mostly robust against race conditions, but leaves artifacts if `kubectl scale` fails mid-flight. |
| Maintainability    | A | Functions are clean, modularized, and have well-defined error propagation. |
| Handoff-readiness  | A | Documentation and runbooks updated properly. |

### Verdict
PASS WITH GAPS

### Recommended next steps
- Update `_blocking_pods` and `open_window` to correctly parse and evaluate `matchExpressions` alongside `matchLabels`.
- Modify the `close_window` wait loop to compare the live `want` replicas with the git-declared replicas instead of strictly demanding `want > 0`.
- In `open_window`, implement an automatic rollback of the Application patch if the `kubectl scale` command fails, preventing the window from becoming stuck if the initial deploy fails.

`/spec archive` is advisable in the current state since all Major findings are THEORETICAL and the implementation behaves correctly for all current workloads in the repository. Recommendations can be addressed in follow-up tickets.
