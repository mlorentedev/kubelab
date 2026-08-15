---
tags: [spec, tasks]
created: "2026-08-14"
---

# Tasks - OBS-010-quota-utilization-alert

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from origin/master: `feat/OBS-010-quota-utilization-alert` ✓ 2026-08-14
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-08-14 — drafted directly (grounded in IDP-031/OBS-007's own measured evidence, no open questions requiring a user call), reviewed, `[AGENT-DRAFT]` tags removed
- [x] No open questions left in `proposal.md` "Risks / open questions" ✓ 2026-08-14 — all five risks have a stated, evidence-backed mitigation

> **RBAC preflight, measured 2026-08-14 (before any manifest, not after `forbidden`):** `kubectl auth can-i create {roles,rolebindings} -n kubelab --as=system:serviceaccount:kubelab:argocd-manager` -> **no** on both, in staging. `serviceaccounts`/`cronjobs`/`configmaps` already covered. So `spoke-rbac.yaml`'s `argocd-manager-write` role needs a new `apiGroups: ["rbac.authorization.k8s.io"]` block for namespaced `roles`/`rolebindings` before this spec's own RBAC objects can deploy — this is task 1, not an afterthought.

## Implementation

### Part 1 — the emitter and the RBAC it needs, proven in staging

- [x] [AC1] Add `roles`/`rolebindings` (namespaced, `rbac.authorization.k8s.io`) to `infra/k8s/argocd/spoke-rbac.yaml`'s `argocd-manager-write` role. Comment why — the same "reads are wildcarded, writes are enumerated, a new kind is invisible until Argo tries it" note IDP-031 already left on this file applies again. ✓ 2026-08-14 — **also needed a separate `bind` verb grant**, not anticipated in the original plan: creating a Role and a RoleBinding referencing it in the SAME apply triggers K8s's privilege-escalation check, which fetches the Role to compare permissions — under `--dry-run=server` that Role was never persisted, so the fetch 404s (`NotFound`, not `Forbidden` — does not read as an RBAC gap at first glance). `bind` skips the comparison. Caught by the dry-run itself, not assumed away.
- [x] [P] [AC1] Add `tests/infra/test_quota_alerting.py`: assert `ServiceAccount/quota-watcher`, `Role/quota-watcher`, `RoleBinding/quota-watcher`, and `CronJob/quota-watcher` all exist in `kubelab`, and the Role's rule is scoped to exactly `get` on `resourcequotas`/`kubelab-quota` (not a wildcard — the RBAC over-scope this test exists to catch). **Fails now.** ✓ 2026-08-14
- [x] [AC1] Add `infra/k8s/base/services/quota-watcher.yaml` (ServiceAccount + Role + RoleBinding + CronJob, `*/5 * * * *`, `automountServiceAccountToken: true` with the comment explaining why this CronJob is the deliberate exception to the fleet's disable-it norm). Register in `base/kustomization.yaml`'s `resources:`. ✓ 2026-08-14 — one round-trip fix needed: a shell line-continuation inside the emitter's `echo` broke the surrounding YAML block scalar's indentation (kustomize failed with a parse error before this was ever deployed); re-indented and re-verified both JSON validity and YAML parseability before redeploying.
- [x] [AC1] Deploy to staging (`make deploy-k8s ENV=staging`), trigger one run on demand (`kubectl create job --from=cronjob/quota-watcher`), and confirm the test from above passes and the job's pod logs contain two structured JSON lines (`requests.memory`, `limits.memory`) whose `used_mi`/`hard_mi`/`pct` match `kubectl get resourcequota kubelab-quota -o json`'s own numbers to the Mi. ✓ 2026-08-14 — first run caught a real test-design flaw: the triggered test job's own pod (32Mi request) is Running and self-counted while the emitter queries the quota, so an exact-equality assertion against a pre-job snapshot failed by exactly 32Mi. Fixed with a bound derived from the job's own declared footprint (32Mi requests / 64Mi limits), not a blind tolerance widening. 5/5 passing.

### Part 2 — the alert rules, proven against the provisioning API

- [x] [P] [AC2] Add `TestQuotaUtilizationRules` to `tests/infra/test_grafana_alerting.py`, reusing the existing `grafana_api` fixture: both rules provisioned, `for: "5m"`, `noDataState: Alerting`, `execErrState: Alerting`, and the policy/contact-point wiring already proven generically by `TestAlertDelivery` covers delivery — no need to re-test that here. **Fails now.** ✓ 2026-08-14
- [x] [AC2] Add `infra/k8s/base/services/grafana-alerting/quota-rules.yaml` (new file, own `quota` group — does not touch OBS-007's `rules.yaml`) with both rules' full A/B/C structure (LogQL `max_over_time` + `unwrap pct`, reduce, threshold `gt 80`). Register in `base/kustomization.yaml`'s `grafana-alerting` `configMapGenerator` `files:` list. ✓ 2026-08-14
- [x] [AC2] Deploy to staging, restart Grafana to pick up the new ConfigMap hash, confirm the test passes against the provisioning API. ✓ 2026-08-14 — ConfigMap hash-suffix rolled Grafana automatically, no manual restart needed. 8/8 passing in `test_grafana_alerting.py` (OBS-007's 5 + OBS-010's 3), zero regression.

### Part 3 — the two dynamic behaviors, exercised rather than assumed

- [x] [AC3] Reproduce IDP-031's surge drill in staging (`make deploy-k8s ENV=staging` + `rollout restart` of all deployments) and watch both rules' state via the provisioning API (or the alerting UI) through and after the restart. Record the peak `pct` observed and confirm neither rule enters `Alerting` — matching IDP-031's own one-time-measurement treatment of its surge case (no permanent test; the `for: 5m` mechanism is evaluated once, empirically, under real load). ✓ 2026-08-14 — **first pass caught a real bug**: the rule fired for real (see verification.md), root-caused to `max_over_time` letting a spike linger for the full 10-minute window regardless of current value. Fixed (`last_over_time`, commit `6cef9a4`, regression test added), re-exercised clean: peak 88.39% on `limits.memory`, both rules reached `pending` at worst, resolved to `inactive`, never `firing`.
- [x] [AC4] In staging only: suspend `quota-watcher` (`kubectl patch cronjob quota-watcher -p '{"spec":{"suspend":true}}'`), wait past one `for: 5m` window with no fresh log lines, confirm both rules move to `Alerting` via the provisioning API, then un-suspend and confirm they return to `Normal` once fresh data arrives. A deliberate, scoped, staging-only fault injection — never run in prod. ✓ 2026-08-14 — both rules reached `firing`; un-suspended, seeded fresh data on demand, both resolved to `inactive` at 06:23:40. Confirmed not-suspended afterward as a safety check.

### Part 4 — prod (post-merge)

- [x] [AC1] [AC2] ✓ 2026-08-14 — ran once aws1 returned. `register-spoke ENV=prod` applied exactly one changed object (`clusterrole/argocd-manager-write configured`); Argo CD's automated sync then applied the manifests without needing `deploy-k8s`, and `quota-watcher`'s CronJob, ServiceAccount, Role and RoleBinding are all `Synced` in prod. Full before/after transcript in `verification.md` § *Part 4 — prod*, including why `deploy-k8s` was not run and why prod is still `OutOfSync` on an unrelated leftover PVC. After merge: `make register-spoke ENV=prod` **first** — `spoke-rbac.yaml` is outside the Kustomize overlay `deploy-k8s` applies, so the `bind`/`roles`/`rolebindings` grants this spec added will not exist in prod until this runs (preflight-checked 2026-08-14: all three `no` in prod, as expected — staging-only until this step). Then `make deploy-k8s ENV=prod`, confirm `quota-watcher` and both rules are live, and that the AUTH-002 (#951) skip already affecting OBS-007's own prod tests applies identically here — not a new gap this spec introduces, cite it rather than re-diagnose it.

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test ✓ 2026-08-14
- [x] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command ✓ 2026-08-14 — f3/f4 corrected from a vacuous `true` placeholder to real `pytest -k` selections after review
- [x] Type checks pass ✓ 2026-08-14
- [x] Lint passes ✓ 2026-08-14
- [x] No unrelated changes in the diff (no scope creep) ✓ 2026-08-14
- [x] `verification.md` filled in ✓ 2026-08-14 — includes the `make test-infra ENV=staging` aws1 caveat (pre-existing, unrelated, see Test status)
- [x] PR opened referencing this spec folder ✓ 2026-08-14

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/<feature-id>/features.json`):

```json
[
  {
    "id": "OBS-010-quota-utilization-alert-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
