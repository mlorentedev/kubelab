---
id: "OBS-009-kube-system-limitrange"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-08-13"
issue: "kubelab#924"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# OBS-009: Kube-system LimitRange

> **Naming**: file lives at `<repo>/specs/<feature-id>/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #924: OBS-009: Traefik and svclb run unbounded in kube-system, outside any quota -->

Six containers in `kube-system` declare no memory limit and five declare no memory request — including Traefik, the single ingress path for every route in the estate. A memory leak or a traffic spike in Traefik has no ceiling, and because it has no request either, the scheduler treats it as free and the kubelet treats it as `BestEffort` — first in line for eviction under node pressure, which is the wrong priority for the component whose failure takes down everything behind it.

This is not a preference among several fixes for `svclb`: verified directly in K3s's `pkg/cloudprovider/servicelb.go`, the generated DaemonSet's container spec carries no `Resources` field at all, and the only two supported annotations (`priorityclassname`, `tolerations`) don't cover it. A namespace `LimitRange` is the only mechanism that exists to bound it — not the best of several options.

It also makes an existing number honest: #811's `kubelab` `ResourceQuota` ceiling reserves ~0.17Gi of node capacity for `kube-system`, computed from *declared* resources. That figure understates real usage precisely because the biggest consumer (Traefik, 149–170Mi observed at rest, 2026-08-13) declares nothing — the reservation has been optimistic by an unknown amount since #811 shipped.

## What

A `LimitRange` in `kube-system` supplies `defaultRequest.memory` and `default.memory` for any container that omits them. Applied via the `cluster_bootstrap` SSOT (new entry in `common.yaml`, no `version`, no `render`, `optional: false`) — **not** through the `kubelab`-scoped Kustomize overlay, whose `namespace: kubelab` override would silently rewrite this object's namespace if it were registered there.

Three observable changes:

1. A pod submitted to `kube-system` with no `resources` block is admitted and comes up carrying the defaults, instead of running unbounded.
2. After a controlled restart of the affected workloads (`traefik`, `svclb-traefik`, `local-path-provisioner`, `metrics-server`), `kubectl get pods -n kube-system -o json` shows zero containers with no memory limit.
3. Traefik and `svclb` move out of `BestEffort` QoS — they carry a memory request, so the scheduler and the eviction ranking both account for them correctly.

## Out of scope

- **A `ResourceQuota` on `kube-system`.** A quota rejects at admission; in a system namespace that means a K3s upgrade (or any control-plane restart) redeploying `coredns`/`traefik`/`metrics-server` could fail to come back up if the namespace is full. This spec's whole point is visibility and a floor, not a ceiling with rejection semantics — the wrong tool for a namespace that isn't ours to break. Answers the ticket title without building the dangerous half of it.
- **Traefik's own explicit `resources` block.** Settable via the `HelmChartConfig` Ansible already templates (`infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2`), but that file is outside this lane's file ownership for this work cycle (two other lanes are active in `infra/ansible/`, per the session's kickoff). Deferred to a follow-up ticket. This spec's generous default limit is the interim safety net, not a replacement for a value tuned specifically for Traefik.
- **CPU dimensions (`requests.cpu`, `limits.cpu`).** Same compressibility argument as IDP-031 (#811): CPU throttles rather than kills, and nothing measured here shows a CPU-driven failure. Deferred on the same evidence standard, not overlooked.
- **Disabling or replacing `servicelb`.** Out of scope entirely — a platform-level decision with its own tradeoffs (losing the built-in LB), not something this ticket's problem (unbounded memory) requires.

## Risks / open questions

- **The default limit must clear Traefik's realistic peak, not just its current idle usage.** A `LimitRange` cannot be scoped per-workload — the moment Traefik's pod restarts under this change, it inherits the same default as `svclb`. Measured 2026-08-13: Traefik uses 149Mi (staging) / 170Mi (prod) at rest, with no production traffic load exercising it. Undersizing the limit here doesn't just fail to help — it actively OOMKills the ingress under exactly the traffic spike the parent ticket worries about. The default must be sized for the biggest inheritor, deliberately asymmetric from the request default (small, `svclb`-tier).
- **The manifest must never be registered in `infra/k8s/base/kustomization.yaml`.** The base Kustomization carries `namespace: kubelab`, which rewrites `metadata.namespace` on every resource listed in it — a `kube-system` LimitRange registered there would silently become a second `kubelab` LimitRange and never reach the namespace it's meant to protect. Mitigation: apply exclusively through `cluster_bootstrap`, and comment the manifest file itself with why it must stay unregistered, so a future "helpful" cleanup doesn't re-add it to `resources:`.
- **The request-must-not-exceed-limit trap, mirrored from IDP-031's own pre-flight.** Any `kube-system` container that already declares `requests.memory` above the chosen default limit, with no limit of its own, would be *rejected* at next admission — the object meant to protect the namespace breaking it instead. Measured 2026-08-13, both clusters: `coredns` is fully bounded already (70Mi req / 170Mi lim, unaffected by defaults). `metrics-server` declares `requests.memory: 70Mi` with no limit — safe under any default limit above 70Mi, which the chosen value clears comfortably. Zero containers in the danger category today; this is a point-in-time measurement, not a permanent guarantee (a K3s version bump could add a new bundled component with a higher declared request).
- **The prod path is imperative, not GitOps, unlike everything else this lane has shipped.** `cluster_bootstrap` entries are applied outside the Argo CD overlay by design (ADR-047/TOOL-009) — `_apply_cluster_bootstrap` runs with full operator privilege, deliberately not impersonated (TOOL-029), because cluster-scoped bootstrap needs privilege the least-privilege spoke role doesn't have. Consequence: prod only gets this object via an explicit `make bootstrap-k8s ENV=prod` (or a full `make deploy-k8s ENV=prod`, which calls it as a step) run after merge — Argo CD's `selfHeal` does not apply here, and a hand-deleted object stays gone until the next manual run. No spoke-RBAC change and no sync-wave ordering needed (single object, no ordering dependency like IDP-031's LimitRange/Quota pair).
- **Existing pods keep running unbounded until they restart.** The LimitRange only affects admission of new pods — `traefik`, `svclb-traefik`, `local-path-provisioner`, and `metrics-server` (the fourth unbounded workload, also named in the parent ticket's own measurement table — initially missed when drafting this list, caught by the Part-2 assertion rather than by re-reading the proposal) all need an explicit rollout/restart after the object lands to actually pick up the defaults, and restarting Traefik briefly interrupts ingress. This must be a deliberate, scheduled task in `tasks.md`, not an assumption.

## Acceptance criteria

- [ ] A `LimitRange` exists in `kube-system` supplying `defaultRequest.memory: 64Mi` and `default.memory: 384Mi`, applied via the `cluster_bootstrap` SSOT and absent from `infra/k8s/base/kustomization.yaml`'s `resources:` list.
- [ ] A pod submitted to `kube-system` with no `resources` block is admitted (`--dry-run=server`) and comes back carrying the defaulted request and limit.
- [ ] After a controlled restart of `traefik`, `svclb-traefik`, `local-path-provisioner`, and `metrics-server`, `kubectl get pods -n kube-system -o json` shows zero **Running** containers with no memory limit, and no Running pod reports `BestEffort` QoS.
- [ ] The restart completes cleanly and ingress keeps serving throughout — reuse an existing e2e health check as the do-no-harm signal, exercised rather than assumed.

## References

- Bitácora board: **kubelab#924** (see the `issue:` frontmatter field)
- **kubelab#811 (IDP-031)** — the sibling `LimitRange`+`ResourceQuota` pattern in the `kubelab` namespace this spec mirrors, one namespace over. Its ceiling arithmetic is the thing this spec makes honest.
- `k3s-io/k3s` `pkg/cloudprovider/servicelb.go` — source-verified 2026-08-13: no `Resources` field on the generated `svclb` DaemonSet container spec, no annotation covers it.
- `infra/ansible/roles/k3s_server/templates/traefik-helmconfig.yaml.j2` — the SSOT home for Traefik's own explicit `resources`, out of scope here, tracked in a follow-up ticket referencing #924.
- ADR-047 / TOOL-009 — the `cluster_bootstrap` SSOT this spec's manifest is applied through.
