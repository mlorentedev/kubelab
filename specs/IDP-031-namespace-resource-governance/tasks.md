---
tags: [spec, tasks]
created: "2026-08-09"
---

# Tasks - IDP-031-namespace-resource-governance

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers:**
> - `[P]` — no dependency on another unchecked task, safe to run in parallel.
> - `[AC<n>]` — helps satisfy acceptance criterion #`<n>` from `proposal.md`.

> **The ordering constraint governs this whole list.** A `ResourceQuota` rejects any pod that omits a dimension it constrains, and `apprise`/`crowdsec` have initContainers that declare nothing. The `LimitRange` must be live and verified *before* the quota exists — which is why tasks 2-5 fully land and validate the `LimitRange` before task 6 introduces the quota at all. Do not collapse them into one commit "since they're both small". The whole risk of this spec lives in that seam.

## Setup

- [x] Branch created from main: `chore/IDP-031-namespace-resource-governance` ✓ 2026-08-09
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-09
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-08-09 — unblocked by PR #920 (the ADR-028 amendment this spec's shared-ceiling premise cites) merging

## Implementation

### Phase 1 — LimitRange alone, proven before the quota exists

- [x] [P] [AC1] Add `TestNamespaceGovernance` to `tests/infra/test_k3s.py` asserting the `kubelab` namespace has a `LimitRange` with `defaultRequest.memory: 128Mi` and `default.memory: 256Mi`. Reuses the existing `_kubectl` / `require_kubeconfig` / `env` helpers. **Fails now** — no LimitRange exists in either cluster. ✓ 2026-08-09 — observed failing first (`No LimitRange in the kubelab namespace`), which is what makes it a check
- [x] [AC1] Add `infra/k8s/base/governance/limitrange.yaml` (namespace `kubelab`, `type: Container`) and register it in `base/kustomization.yaml`. Values from proposal → The chosen values. No quota in this commit. ✓ 2026-08-09 — verified against the **rendered** output of both overlays, not the source file
- [x] [AC1] [AC2] Deploy to staging via the ADR-037 flow (`make deploy-k8s ENV=staging`) and confirm the test from the first task now passes against staging. ✓ 2026-08-09 — the LimitRange applied; the deploy as a whole exits non-zero on an unrelated pre-existing defect (#938, Homepage ConfigMap over the client-side-apply annotation limit), and `kubectl apply` is per-object so no other resource was affected
- [x] [AC2] [AC6] Verify the defaulting actually lands on the two unbounded initContainers: `rollout restart` `apprise` and `crowdsec`, then assert each pod's `spec.initContainers[*].resources` reports 128Mi/256Mi where it previously reported nothing. **This is the task that proves the quota will be safe to add** — if it fails, stop; adding the quota next would break the namespace. ✓ 2026-08-09 — captured before/after in one run: both `UNBOUNDED` → both `128Mi`/`256Mi`, both rollouts healthy
- [x] [AC2] Extend the test with the generic case: apply a throwaway pod carrying no `resources` block, assert it is admitted and comes up with the defaulted request and limit, then delete it. Keeps the criterion honest for future manifests, not just for today's two pods. ✓ 2026-08-09 — **implemented as a server-side dry run rather than create-then-delete.** `--dry-run=server` traverses the real admission chain, of which LimitRanger is a member, and returns the mutated object without persisting it. That tests the only thing which can reject a pod (admission), keeps the whole infra suite read-only, and therefore stays safe to run against prod — a create-then-delete test would mutate prod on every `make test-infra ENV=prod`, and its extra coverage would be the scheduler, which is not what a LimitRange governs.

**Pre-flight added during implementation (not in the original plan, and it can veto the phase).** A `LimitRange` is not purely additive: `default` is injected as a limit into any container that omits one, and `request <= limit` is validated afterwards. So a container declaring `requests.memory` above 256Mi with no limit would be *rejected* — the object meant to protect the namespace breaking pods. The mirror case is a declared limit below the 128Mi `defaultRequest`. Both were measured across both clusters before the manifest was written: 0 containers in either category, 35 safe, only the 2 known unbounded initContainers. Had that set been non-empty, the chosen values would have needed revisiting first.

### Phase 2 — ResourceQuota, once the floor is proven

- [ ] [AC3] Extend `TestNamespaceGovernance` to assert a `ResourceQuota` with `requests.memory: 4Gi` and `limits.memory: 7Gi`, and that `kubectl describe ns kubelab` reports used-vs-hard for both. **Fails now.**
- [ ] [AC3] Add `infra/k8s/base/governance/resourcequota.yaml` and register it. **Carry the ordering mitigation in the same commit**, because Kustomize emits `ResourceQuota` before `LimitRange` (verified — see Risks): annotate the `LimitRange` with `argocd.argoproj.io/sync-wave: "-1"` so the GitOps path applies it first, and confirm the wave is respected rather than assumed.
- [ ] [AC3] [AC6] Deploy to staging, confirm the quota test passes and that `apprise`/`crowdsec` are still `Running` with the quota active — the ordering regression test, now with both objects present.
- [ ] [AC4] Add a test asserting rejection: request a pod whose memory limit exceeds the remaining headroom, assert the API error is a quota error and that its message names the exceeded resource (not merely that creation failed — a pod can fail for many reasons, and a test that accepts any failure would pass against a broken cluster).

### Phase 3 — the surge case, exercised rather than reasoned about

- [ ] [AC5] Run a full `make deploy-k8s ENV=staging` followed by `rollout restart` of **all** deployments, and assert no pod is left `Pending` with a quota reason. Only 4 of 14 deployments surge (the rest are `Recreate`), so the expected peak is +1.25 Gi of limits against 7 Gi — but the point of this task is to measure it, not to trust that arithmetic.
- [ ] [AC5] Record the observed peak `used` against `hard` from `kubectl describe ns kubelab` during the restart. This is the number #918 will alert on, and the only empirical check that the 5.7% limits headroom is real.

### Phase 4 — prod

- [ ] [AC6] Merge to master and let Argo CD sync prod (`selfHeal: true` per ADR-037). Confirm the sync applied the `LimitRange` in an earlier wave than the quota, and that `apprise`/`crowdsec` stay `Running` through it — the prod half of the ordering regression, and the one place the mitigation is load-bearing and cannot be re-run by hand.
- [ ] [AC3] Confirm prod reports usage against the ceiling, and that the prod-only backup CronJob's next 03:00 UTC run is admitted (its 0.5 Gi is inside the window, but it has never run under a quota).

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] `make test-infra ENV=staging` and `ENV=prod` green
- [ ] Type checks pass (`make type`)
- [ ] Lint passes (`make lint`)
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
    "id": "IDP-031-namespace-resource-governance-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
