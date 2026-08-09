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

Note on what change 1 does *today*: measured against live staging, **every running container already declares memory limits** — zero containers are unbounded. The `LimitRange` therefore remediates nothing at the moment; its whole value is as a ratchet, so the property cannot be lost silently by a future manifest. That is a weaker justification than "it fixes a live problem" and the spec should not claim otherwise.

## Out of scope

- **Any quota on `limits.cpu`.** CPU is compressible: exhausting it throttles rather than kills. Measured today, `limits.cpu` sums to 7.10 against 4 allocatable in both environments — that overcommit is healthy, not debt. A `limits.cpu` quota at prod budget would be binding on day one, would block deploys, and buys no protection against the failure mode this spec exists for.
- **A `requests.cpu` quota.** Safe today (every container declares it) and it would protect scheduling, but it addresses no observed failure. Deferred deliberately, not overlooked — it can be added later on evidence.
- **Alerting on quota utilization.** Different subsystem, and it cannot be built before the quota exists. Tracked as #918, which likely shares a notification path with #799.
- **Raising prod's capacity.** A capacity decision, not a governance one. Nothing measures utilization over time yet, so there is no basis for it — this spec produces that basis.
- **A tighter quota in staging than prod.** Considered and rejected: see the Risks note on why detection does not belong in an admission gate.

## Risks / open questions

- **A `ResourceQuota` on a dimension rejects every pod that does not declare that dimension.** This is the dependency that makes ordering non-negotiable: the `LimitRange` must default every dimension the quota constrains, and must land before or with the quota. Applied in the wrong order this spec is itself the outage. Not theoretical — `homepage` is the single container in both environments that omits `limits.cpu`, and it is why a CPU quota is out of scope rather than merely deferred.
- **Surge headroom is the sizing constraint, not steady state.** `rollout restart` admits the new pod before the old one terminates. Largest pod limit is 0.50 Gi; a full `make deploy-k8s` restarts several deployments concurrently. A ceiling set at 6 Gi against 4.88 Gi of current limits leaves 1.12 Gi — roughly two concurrent surges — which would stall a normal deploy. The ceiling must clear current limits **plus** realistic concurrent surge, and the deploy flow is the thing exercised most often.
- **The exact ceiling is not yet fixed.** Measured inputs: prod allocatable 7.55 Gi, staging 11.47 Gi, current limits 4.88 Gi in both, and the `kubelab` quota must also leave room for `kube-system` on the same node, which a namespace quota does not count.
- **Detection must not be built into the gate.** A quota can only reject, never warn, so making staging tighter than prod would convert every early signal into a blocked deploy. The predictable end state is that the number gets raised to unblock work and stops meaning anything — the same dynamic as #912. Early warning belongs in utilization alerting.
- **Open, and it moves the numbers: #917.** ADR-028 decided that observability runs on prod and not staging, with a circularity argument. Staging runs Grafana, Loki and Vector anyway. The "identical workloads" measurement this spec rests on is therefore a measurement of the current *drift*, not of the intended topology. If #917 resolves toward enforcing the ADR, staging's workload shrinks and the single shared ceiling stops being the obvious design. Either resolve #917 first, or record here as a deliberate choice that IDP-031 sizes for observed reality.

## Acceptance criteria

- [ ] A `LimitRange` in the `kubelab` namespace supplies default memory requests and limits, and defaults exist for **every** dimension the `ResourceQuota` constrains.
- [ ] A pod submitted with no `resources` block is admitted and comes up carrying the defaulted memory request and limit.
- [ ] A `ResourceQuota` constrains `requests.memory` and `limits.memory` at a single value applied to both environments, and `kubectl describe ns kubelab` reports usage against it.
- [ ] A workload that would push the namespace past the ceiling is rejected at admission with an explicit quota error, and the rejection names the exceeded resource.
- [ ] A full staging deploy followed by a `rollout restart` of all deployments completes with no pod stuck `Pending` on quota — the surge case, exercised rather than reasoned about.

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADR: `<repo>/docs/adr/adr-XXX.md` (if any)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
