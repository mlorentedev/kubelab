---
id: "IDP-031-namespace-resource-governance"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-08-09"
issue: "kubelab#811"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# IDP-031: Namespace Resource Governance

## Why

<!-- from issue #811: IDP-031: namespace-level resource governance (ResourceQuota + LimitRange) -->

The `kubelab` namespace has no aggregate ceiling and no default resource floor. Both gaps are in scope, because they fail differently: without a `ResourceQuota` the sum of workloads can exhaust the node even when every pod is individually reasonable, and without a `LimitRange` a manifest can ship a container with no limits at all and nothing rejects it.

For this namespace the work is preventive, but the failure mode is not theoretical — resource exhaustion has already happened elsewhere in this estate, on aws1 and on the VPS. The node most exposed here is ace1, a single all-in-one that runs the entire staging cluster with no second node to absorb a starved workload.

The cost of doing nothing is not a crash but a slow one: the next manifest that omits `resources` is accepted silently, and the failure surfaces later as node pressure with no obvious cause.

## What

Three observable changes in the `kubelab` namespace:

1. A container deployed **without** `resources` receives default requests and limits instead of running unbounded.
2. A deployment that would push the namespace past its ceiling is **rejected** with an explicit admission error, instead of being admitted and pressuring the node.
3. `kubectl describe ns kubelab` reports consumption against a ceiling. Today there is nothing to read: the namespace has no `ResourceQuota` and no `LimitRange` at all (verified against staging, 2026-08-09).

Note on what change 1 does *today*. An earlier draft of this spec claimed that every container already declares memory limits, so the `LimitRange` would be a pure ratchet. **That claim was wrong** — it came from a measurement that summed `spec.containers` and never looked at `spec.initContainers`. Re-measured on 2026-08-09 against both live clusters:

| Pod | initContainer | Declared resources |
|---|---|---|
| `apprise` | `seed-config` | **none** |
| `crowdsec` | `inject-whitelist` | **none** |

Two unbounded initContainers, identically in staging and prod. So the `LimitRange` remediates something real, and — more importantly — those two pods are the concrete proof of this spec's central invariant: a `ResourceQuota` on `requests.memory` applied *without* a `LimitRange` in place would **reject `apprise` and `crowdsec` at admission**. The ordering constraint in Risks is not a theoretical precaution; it has two names.

Their effective requests will also move. A pod's effective request is `max(max(init requests), sum(container requests))`, so once the defaults apply, `apprise` rises from its measured 96 Mi to the default request of 128 Mi.

### The chosen values

Decided 2026-08-09 from the measured inputs in Risks. One set, applied to both environments:

| Object | Field | Value |
|---|---|---|
| `ResourceQuota` | `requests.memory` | **4 Gi** |
| `ResourceQuota` | `limits.memory` | **7 Gi** |
| `LimitRange` | `defaultRequest.memory` | **128 Mi** |
| `LimitRange` | `default.memory` | **256 Mi** |

The `limits.memory` ceiling is the load-bearing one, and it is deliberately tight — 7 Gi against a 6.625 Gi floor is 5.7% of headroom. That is the point: prod's node allocates 7.55 Gi and `kube-system` needs ~0.17 Gi of it, so **7 Gi is the largest ceiling that still guarantees the namespace cannot exhaust the node even at full burst**. Choosing headroom above that number would trade away the property the quota exists to provide. The `requests.memory` ceiling carries the comfortable margin instead (4 Gi against a 3.03 Gi floor, +32%), which is the right place for it since requests are what the scheduler actually enforces.

The 128/256 Mi defaults are the tier `postgres`, `gitea`, `authelia` and `crowdsec` already use, so they are calibrated against real workloads in this namespace rather than picked as round numbers.

## Out of scope

- **Any quota on `limits.cpu`.** CPU is compressible: exhausting it throttles rather than kills. Measured today, `limits.cpu` sums to 7.10 against 4 allocatable in both environments — that overcommit is healthy, not debt. A `limits.cpu` quota at prod budget would be binding on day one, would block deploys, and buys no protection against the failure mode this spec exists for.
- **A `requests.cpu` quota.** Safe today (every container declares it) and it would protect scheduling, but it addresses no observed failure. Deferred deliberately, not overlooked — it can be added later on evidence.
- **Alerting on quota utilization.** Different subsystem, and it cannot be built before the quota exists. Tracked as #918, which likely shares a notification path with #799.
- **Raising prod's capacity.** A capacity decision, not a governance one. Nothing measures utilization over time yet, so there is no basis for it — this spec produces that basis.
- **A tighter quota in staging than prod.** Considered and rejected: see the Risks note on why detection does not belong in an admission gate.

## Risks / open questions

- **A `ResourceQuota` on a dimension rejects every pod that does not declare that dimension.** This is the dependency that makes ordering non-negotiable: the `LimitRange` must default every dimension the quota constrains, and must land before or with the quota. Applied in the wrong order this spec is itself the outage. Not theoretical — `homepage` is the single container in both environments that omits `limits.cpu`, and it is why a CPU quota is out of scope rather than merely deferred.
- **Kustomize applies these two objects in exactly the wrong order, by default.** Verified empirically on 2026-08-09: `kubectl kustomize` emits `ResourceQuota` **before** `LimitRange`. This is kustomize's legacy kind-ordering, not filename or name ordering — the check used `zzz-quota` and `aaa-limits` specifically to rule those out, and the quota still came first. So the naive "put both in `base/` and deploy" produces the inverse of the ordering this spec depends on. Two consequences: a brief window during each apply in which the quota is active with no defaults, and — the one that matters — if the `LimitRange` apply *fails* while the quota's succeeded, the namespace is left in precisely the broken state described in the bullet above, permanently and silently until the next pod restart. Mitigation belongs in the implementation, not in a runbook step someone must remember: an Argo CD `sync-wave` on the `LimitRange` for the GitOps path, and applying the `LimitRange` ahead of the quota for the `kubectl apply -k` path.
- **Surge headroom is a sizing constraint, but a smaller one than first assumed.** An earlier draft reasoned that "a full `make deploy-k8s` restarts several deployments concurrently" and put the worst case near a doubling. Measured on 2026-08-09, **10 of the 14 deployments use `strategy: Recreate`**, which terminates the old pod *before* creating the new one and therefore does not surge at all. Only four surge: `web` (0.50 Gi), `api` (0.50 Gi), `homepage` (0.19 Gi), `errors` (0.06 Gi). Worst case, all four at once: **+1.25 Gi of limits, +0.59 Gi of requests.** The ceiling must still clear current usage plus that window, but the window is bounded and known rather than estimated.
- **The ceiling derivation.** Fixed 2026-08-09 at 4 Gi requests / 7 Gi limits (see What → The chosen values) from these measured inputs, identical in both environments:

  | Input | Value |
  |---|---|
  | `kubelab` `requests.memory` | 2.312 Gi |
  | `kubelab` `limits.memory` | 4.875 Gi |
  | worst-case concurrent surge | +0.59 Gi requests / +1.25 Gi limits |
  | prod backup CronJob (prod overlay only, 03:00 UTC daily) | +0.125 Gi requests / +0.50 Gi limits |
  | `kube-system` (outside this quota) | 0.137 Gi requests / 0.166 Gi limits |
  | node allocatable | prod 7.55 Gi · staging 11.47 Gi |

  Two notes on that table. The prod backup CronJob can fire concurrently with a deploy, so it belongs in the ceiling window, not outside it. And `kube-system` is *not* counted by a namespace quota — its numbers are there to show what the node must still afford, and they understate it: Traefik and three `svclb` containers in `kube-system` declare no requests or limits at all (tracked separately; different namespace, out of scope here).
- **The first raise is already foreseeable, and that is not the #912 dynamic.** ADR-032 plans Prometheus and Alertmanager into the shared base. When MET-001 lands, the ceiling rises because the workload set genuinely grew — a deliberate, evidence-backed raise, unlike a number raised to unblock a deploy. Recording it here so that when it happens it reads as designed rather than as the ceiling losing meaning.
- **Detection must not be built into the gate.** A quota can only reject, never warn, so making staging tighter than prod would convert every early signal into a blocked deploy. The predictable end state is that the number gets raised to unblock work and stops meaning anything — the same dynamic as #912. Early warning belongs in utilization alerting.
- **Resolved, and it settles the numbers: #917.** ADR-028 decided that observability runs on prod and not staging, with a circularity argument, while staging runs Grafana, Loki and Vector anyway — so the "identical workloads" premise was measuring drift rather than intent. Resolved by amending the ADR — **#920, merged 2026-08-09**: the ADR's bullet conflated *where the monitoring of record lives* (prod plus the RPi3 — unchanged) with *which manifest set each environment deploys* (staging mirrors prod's base, per the ADR-037 validation flow). Observability manifests stay shared. The identical footprints are therefore a deliberate architectural property, and a single ceiling applied to both environments is the design that follows from it. No longer open.

## Acceptance criteria

- [ ] A `LimitRange` in the `kubelab` namespace supplies `defaultRequest.memory: 128Mi` and `default.memory: 256Mi`, and defaults exist for **every** dimension the `ResourceQuota` constrains.
- [ ] A pod submitted with no `resources` block is admitted and comes up carrying the defaulted memory request and limit.
- [ ] A `ResourceQuota` constrains `requests.memory` at 4 Gi and `limits.memory` at 7 Gi, the same values in both environments, and `kubectl describe ns kubelab` reports usage against them.
- [ ] A workload that would push the namespace past the ceiling is rejected at admission with an explicit quota error, and the rejection names the exceeded resource.
- [ ] A full staging deploy followed by a `rollout restart` of all deployments completes with no pod stuck `Pending` on quota — the surge case, exercised rather than reasoned about.
- [ ] `apprise` and `crowdsec` — the two pods whose initContainers declare no resources — are admitted and reach `Running` with both environments' quota active, and their initContainers report the defaulted values. This is the case that would fail if the `LimitRange` were absent or landed after the quota, so it is the regression test for the ordering constraint, not a restatement of criterion 2.

## References

- Bitácora board: **kubelab#811** (see the `issue:` frontmatter field)
- **#917 / PR #920** — the ADR-028 amendment this spec's "identical workloads in both environments" premise rests on. Must merge before this spec is frozen.
- `docs/adr/adr-037-*` — the staging-validates-prod flow that makes a single shared ceiling the right design, and that dictates the validation order in `tasks.md`.
- `docs/adr/adr-024-pvc-backup-strategy.md` — the prod backup CronJob whose 0.5 Gi limit is inside the ceiling window.
- `docs/adr/adr-032-observability-stack-execution.md` — Prometheus and Alertmanager are planned into the shared base; MET-001 is the foreseeable first raise of this ceiling.
- **#918 (OBS-008)** — quota utilization alerting. Where the early warning lives, deliberately *outside* this admission gate.
- Measurement method: `kubectl get pods -o json` summed over `spec.containers` **and** `spec.initContainers`, both clusters, 2026-08-09. Summing only `spec.containers` is what produced the false "zero unbounded containers" claim in the first draft.
