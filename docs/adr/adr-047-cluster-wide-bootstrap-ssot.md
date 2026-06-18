---
id: "adr-047-cluster-wide-bootstrap-ssot"
type: adr
status: accepted
created: "2026-06-16"
accepted: "2026-06-17"
tags: [architecture, gitops, argocd, bootstrap, operators, ssot, toolkit, k8s]
related:
  - adr-023-hub-spoke-multicloud-gitops
  - adr-021-helm-k8s-packaging
  - adr-036-shared-infra-namespace
  - adr-037-environment-promotion-strategy
  - adr-041-agent-fleet-vpn-segmentation
  - adr-046-gitops-delivery-promotion-strategy
issue: "mlorentedev/knowledge#118"
---

# ADR-047: Cluster-Wide Bootstrap Layer — SSOT-Declarative Operator Installation

## Status

Accepted — 2026-06-17 (supersedes the 2026-06-16 draft; original premise corrected after a code + vault audit — see Context).

## Context

kubelab runs a deliberately **layered GitOps** model:

- **Apps layer** — one Argo CD `Application` per environment (`infra/k8s/argocd/applications/{staging,prod}.yaml`) syncs the Kustomize overlay `infra/k8s/overlays/{env}` into the `kubelab` namespace. The overlay applies a global `namespace: kubelab` transformer to everything it composes.
- **Least-privilege Argo CD** — the spoke RBAC is scoped: Argo CD can *manage* resources only in the `kubelab` namespace; cluster-wide access (namespaces, nodes, CRDs) is **read-only** (`runbook-argocd-spoke-management`, and ADR-041's "scoped RBAC tokens" dominant-pattern stance). Argo CD is therefore **structurally unable** to create CRDs, ClusterRoles, or workloads in other namespaces.

Consequently, cluster-scoped foundational resources are applied **imperatively, outside the overlay**. A **code + vault audit during implementation (2026-06-17) corrected this ADR's original "two static special-cases" premise**:

- The `_get_traefik_config_path()` branch in `toolkit/cli/infra.py` (`k8s_deploy` step 3) is **dead code** — its target `infra/k8s/base/traefik-config.yaml` was removed in ADR-020 Phase 3; the Traefik HelmChartConfig is now templated by Ansible (`k3s_server/templates/traefik-helmconfig.yaml.j2`) into the node's K3s auto-deploy manifests dir. The branch returns `None` and never fires.
- `coredns-custom` (the K3s pod-hairpin DNS ConfigMap) is the **only** real outside-overlay apply today, and it lives in `make deploy-external`, **not** `deploy-k8s` (the docs claiming otherwise are stale — see Consequences). It is **not** a static manifest: it carries a `RESOLVE_RPI4_TAILSCALE_IP` placeholder resolved at deploy time via MagicDNS (`dig | sed`), because RPi4's Tailscale IP rotates on re-registration (ADR-025; `lessons.md` 2300-2306). The same placeholder pattern recurs inline in **three** Makefile sites: coredns/rpi4 and the uptime-kuma EndpointSlice/rpi3 (`deploy-external`), and the argocd EndpointSlice/aws1 (`_deploy-argocd-helm`).

So the real problem is not "two static special-cases" but **inline, untested `dig | sed | kubectl` shell scattered across the Makefile**, with no shared, SSOT-driven abstraction — and `agent-sandbox` adds a fourth cluster-wide need (a static, *versioned* operator) that the current ad-hoc approach cannot absorb cleanly.

The trigger for this ADR is integrating **`kubernetes-sigs/agent-sandbox`** (the Kubernetes runtime substrate for iris SDD-034c) — a cluster-scoped operator (CRDs + ClusterRole + its own `agent-sandbox-system` namespace + a controller Deployment). It is the **third** cluster-wide component. Adding it as a third hardcoded special-case is the inflection point where two exceptions become an un-managed pattern, and it violates the SSOT/declarative principle the project enforces everywhere else (ADR-036 shared-infra SSOT; the toolkit config-generation model). It would also break if naively dropped into the overlay: the `namespace: kubelab` transformer would rewrite the controller's namespace and break the operator.

## Decision

### D1 — Keep the architecture: least-privilege Argo CD + a separate cluster-wide bootstrap layer

The split (Argo CD for namespaced workloads + an imperative bootstrap layer for cluster-scoped foundations) is the mainstream enterprise "platform/addons vs apps" pattern and is **reaffirmed**, not changed. Granting the apps Argo CD cluster-admin so it can "GitOps everything" is **rejected**: it widens the blast radius and reverses the deliberate least-privilege posture of ADR-041. The architecture is correct; only its *implementation* is the problem.

### D2 — Make the bootstrap layer SSOT-declarative

Cluster-wide components are declared in `infra/config/values/common.yaml` under a `cluster_bootstrap:` list. Each entry has `{ name, namespace, manifest }` plus **optional** fields: `version` (only for vendored, *versioned* operators — drives the refresh target), `render` (a `RESOLVE_*` → MagicDNS-name map resolved at deploy time, preserving the ADR-025 dynamic-IP pattern), and `optional: true` (skip rather than fail when a render target is unreachable, e.g. RPi4 off). Operator manifests are **vendored, version-pinned, and reviewable** (`infra/k8s/cluster/<name>/`), never fetched from a moving remote at apply time (reproducibility).

The key name `cluster_bootstrap` (not `cluster_operators`) is deliberate: the list mixes versioned operators (`agent-sandbox`) with cluster-wide config (`coredns-custom`), so it names the **layer**, not the resource kind.

### D3 — Generalize via a reusable render-and-apply primitive (kill the inline shell)

A toolkit primitive — `render_and_apply(manifest, render_map, kubeconfig, *, optional, server_side)` — resolves each `RESOLVE_*` placeholder via MagicDNS, substitutes in-memory, dry-runs (`--dry-run=server`), and applies. `toolkit infra k8s deploy` step 3 iterates `cluster_bootstrap` through this primitive (replacing the **dead** `_get_traefik_config_path()`, which is deleted, not migrated — there is nothing behind it). The **three** existing inline `dig | sed | kubectl` Makefile sites (coredns/rpi4, uptime-kuma/rpi3, argocd/aws1) are migrated onto the *same* primitive, so the abstraction is proven across every real case and the Makefile keeps no deploy-time shell.

### D4 — agent-sandbox is the first declared operator

`agent-sandbox` `v0.5.0rc1` (the first published release serving `agents.x-k8s.io/v1beta1`, image `registry.k8s.io/agent-sandbox/agent-sandbox-controller:v0.5.0rc1`) is the first entry. This unblocks iris SDD-034c validation: agents are created as `Sandbox` CRs in `default`, reconciled by the cluster-scoped controller.

### D5 — Full-GitOps addons end-state is descoped (documented, not built)

The recognized enterprise end-state for many operators is a dedicated `cluster-addons` Argo CD `AppProject` with scoped-but-elevated RBAC + sync waves. It is **descoped now**: for ~3 operators on a 1–2 GB hub it is over-engineering, and it reopens the ADR-041 least-privilege RBAC decision. Recorded here as the future option to revisit when operator count/complexity justifies it.

## Rejected alternatives

| Option | Why rejected |
|---|---|
| Third hardcoded special-case for agent-sandbox | Feeds the very antipattern this ADR removes; does not scale. |
| Grant Argo CD cluster-admin / per-component Application | Blast radius; reverses ADR-041 least-privilege; Argo CD spoke RBAC is read-only cluster-wide by design. |
| Helm-via-Kustomize inside the overlay | The overlay's `namespace: kubelab` transformer rewrites the operator's namespace and breaks the cluster-scoped controller. |
| Reference the upstream release manifest by URL | Non-reproducible (moving target); fails offline/air-gapped; not reviewable in a diff. |

## Consequences

- **Positive:** the cluster-wide layer becomes declarative + SSOT + scalable; security posture unchanged; **all** inline `dig | sed | kubectl` deploy shell (3 sites) folded into one *tested* toolkit primitive; the dead traefik branch removed; `coredns-custom` moved to its correct layer (`deploy-k8s` bootstrap), fixing prior doc drift; iris SDD-034c unblocked.
- **Negative / cost:** one new SSOT section + a toolkit primitive + the deploy-step generalization; migrating the argocd/aws1 site brings the hub deploy path lightly into scope; vendored operator manifests need a refresh path (`make sync-operators`, mirroring `sync-k8s-images`).
- **Follow-up:** D5 addons-project ticketed as a future option; CLAUDE.md + `lessons.md` coredns doc drift corrected as part of this change; iris validation depends on this landing.
