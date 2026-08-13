---
tags: [spec, tasks]
created: "2026-08-13"
---

# Tasks - OBS-009-kube-system-limitrange

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from origin/master: `feat/OBS-009-kube-system-limitrange` ✓ 2026-08-13
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-13 — drafted via advisor at the user's request, reviewed and accepted (`[AGENT-DRAFT]` tags removed)
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-08-13 — all five risks have a stated mitigation, none blocking

> **Why the manifest never goes in `infra/k8s/base/kustomization.yaml`.** The base carries `namespace: kubelab`, which rewrites `metadata.namespace` on every resource registered in `resources:`. This whole spec applies through the `cluster_bootstrap` SSOT instead (`common.yaml` + `toolkit/features/k8s_render.py`, the same mechanism `coredns-custom` already uses) — see proposal.md → Risks. Do not "simplify" this by adding the manifest to the Kustomize `resources:` list; that is the one mistake that silently defeats the whole spec.

## Implementation

### Part 1 — the LimitRange, proven in staging

- [ ] [P] [AC1] Add `TestKubeSystemGovernance` to `tests/infra/test_k3s.py` asserting `kube-system` has a `LimitRange` with `defaultRequest.memory: 64Mi` and `default.memory: 384Mi`. Reuses the existing `_kubectl`/`require_kubeconfig`/`env` helpers, targeting `-n kube-system` instead of `-n kubelab`. **Fails now** — no LimitRange exists in `kube-system` in either cluster.
- [ ] [AC1] Add `infra/k8s/base/governance/kube-system-limitrange.yaml` (namespace `kube-system`, `type: Container`, values from proposal.md → Acceptance criteria). Header comment explains why it must never be added to `infra/k8s/base/kustomization.yaml`'s `resources:`.
- [ ] [AC1] Register a `cluster_bootstrap` entry in `infra/config/values/common.yaml` (`name: kube-system-limitrange`, `namespace: kube-system`, `manifest: infra/k8s/base/governance/kube-system-limitrange.yaml`, no `version`, no `render`, `optional: false`).
- [ ] [AC1] Apply to staging via `make bootstrap-k8s ENV=staging` (NOT `deploy-k8s` — this object is cluster-scoped bootstrap, outside the namespaced overlay). Confirm the test from the first task now passes.
- [ ] [AC2] Extend the test with the generic defaulting case: `--dry-run=server` a throwaway pod in `kube-system` carrying no `resources` block, assert it is admitted and comes back with the defaulted request/limit. Same rationale as IDP-031's own defaulting test — traverses real admission (LimitRanger) without persisting, safe against prod.

**Pre-flight, measured 2026-08-13 (see proposal.md → Risks) — do not re-derive, just cite:** `coredns` is fully bounded already (unaffected by defaults). `metrics-server` declares `requests.memory: 70Mi` with no limit — safe under `default.memory: 384Mi` (70Mi < 384Mi, no request-exceeds-limit rejection). Zero containers in the danger category in either cluster.

### Part 2 — the restart, exercised rather than assumed

- [x] [AC3] Restart the affected workloads in staging: `traefik`, `svclb-traefik-<suffix>` (the K3s-generated svclb DaemonSet carries a dynamic name suffix, not the literal `svclb-traefik` — resolve with `kubectl get daemonset -n kube-system` first), `local-path-provisioner`. **Corrected mid-task**: `metrics-server` was missing from this list — it also declares no limit (visible in the parent ticket's own measurement table) and was caught by the assertion in the next task, not by re-reading the proposal. Added and restarted. ✓ 2026-08-13 — all four rolled out cleanly.
- [x] [AC3] Extend the test: assert `kubectl get pods -n kube-system -o json` shows zero **Running** containers with no `resources.limits.memory`, and no Running pod reports `status.qosClass == BestEffort`. Scoped to `Running` deliberately — the two completed `helm-install-*` Job pods predate the LimitRange, are terminal, and are not the steady-state failure mode this spec addresses. ✓ 2026-08-13 — 0 unbounded, 0 BestEffort among Running pods.
- [x] [AC4] Do-no-harm check: run `make test-e2e ENV=staging` immediately after the restart (reuses existing ingress health checks — no new test needed, this criterion is about the restart not breaking what already exists). ✓ 2026-08-13 — 71 passed, 12 skipped (pre-existing, unrelated), 0 failed.

### Part 3 — prod (imperative path, post-merge)

- [ ] [AC1] [AC3] After merge: `make bootstrap-k8s ENV=prod`, then restart the same four prod workloads (`traefik`, `svclb-traefik-<suffix>`, `local-path-provisioner`, `metrics-server`), then re-run the `TestKubeSystemGovernance` assertions against prod. This is NOT GitOps-synced (proposal.md → Risks) — it will not happen on its own.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/<feature-id>/features.json`):

```json
[
  {
    "id": "OBS-009-kube-system-limitrange-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
