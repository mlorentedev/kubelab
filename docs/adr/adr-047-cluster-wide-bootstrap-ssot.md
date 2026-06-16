---
id: "adr-047-cluster-wide-bootstrap-ssot"
type: adr
status: proposed
created: "2026-06-16"
tags: [architecture, gitops, argocd, bootstrap, operators, ssot, toolkit, k8s, draft]
related:
  - adr-023-hub-spoke-multicloud-gitops
  - adr-021-helm-k8s-packaging
  - adr-036-shared-infra-namespace
  - adr-037-environment-promotion-strategy
  - adr-041-agent-fleet-vpn-segmentation
  - adr-046-gitops-delivery-promotion-strategy
issue: "TBD — create bitácora item (mlorentedev/knowledge#NNN)"
---

# ADR-047: Cluster-Wide Bootstrap Layer — SSOT-Declarative Operator Installation

## Status

Proposed — 2026-06-16 (DRAFT, pending review)

## Context

kubelab runs a deliberately **layered GitOps** model:

- **Apps layer** — one Argo CD `Application` per environment (`infra/k8s/argocd/applications/{staging,prod}.yaml`) syncs the Kustomize overlay `infra/k8s/overlays/{env}` into the `kubelab` namespace. The overlay applies a global `namespace: kubelab` transformer to everything it composes.
- **Least-privilege Argo CD** — the spoke RBAC is scoped: Argo CD can *manage* resources only in the `kubelab` namespace; cluster-wide access (namespaces, nodes, CRDs) is **read-only** (`runbook-argocd-spoke-management`, and ADR-041's "scoped RBAC tokens" dominant-pattern stance). Argo CD is therefore **structurally unable** to create CRDs, ClusterRoles, or workloads in other namespaces.

Consequently, cluster-scoped foundational resources are applied **imperatively, outside the overlay**, by `toolkit infra k8s deploy` (step 3, "Apply cluster-wide resources (outside Kustomize namespace override)"). Today that step is **hardcoded to a single file** via `_get_traefik_config_path()` (`toolkit/cli/infra.py`), with `coredns-custom` applied as a second hand-rolled `sed | kubectl apply` step in the Makefile. Two special-cases, no shared abstraction.

The trigger for this ADR is integrating **`kubernetes-sigs/agent-sandbox`** (the Kubernetes runtime substrate for iris SDD-034c) — a cluster-scoped operator (CRDs + ClusterRole + its own `agent-sandbox-system` namespace + a controller Deployment). It is the **third** cluster-wide component. Adding it as a third hardcoded special-case is the inflection point where two exceptions become an un-managed pattern, and it violates the SSOT/declarative principle the project enforces everywhere else (ADR-036 shared-infra SSOT; the toolkit config-generation model). It would also break if naively dropped into the overlay: the `namespace: kubelab` transformer would rewrite the controller's namespace and break the operator.

## Decision

### D1 — Keep the architecture: least-privilege Argo CD + a separate cluster-wide bootstrap layer

The split (Argo CD for namespaced workloads + an imperative bootstrap layer for cluster-scoped foundations) is the mainstream enterprise "platform/addons vs apps" pattern and is **reaffirmed**, not changed. Granting the apps Argo CD cluster-admin so it can "GitOps everything" is **rejected**: it widens the blast radius and reverses the deliberate least-privilege posture of ADR-041. The architecture is correct; only its *implementation* is the problem.

### D2 — Make the bootstrap layer SSOT-declarative

Cluster-wide components are declared in `infra/config/values/common.yaml` under a `cluster_operators:` list — each entry pins `{ name, namespace, version, manifest }` — exactly as image tags/versions are declared today. Their manifests are **vendored, version-pinned, and reviewable** in the repo (proposed: `infra/k8s/cluster/<name>/`), never fetched from a moving remote at apply time (reproducibility).

### D3 — Generalize the apply (kill the special-cases)

`toolkit infra k8s deploy` step 3 iterates the `cluster_operators` list and `kubectl apply --server-side` each vendored manifest, replacing the hardcoded `_get_traefik_config_path()`. `traefik-config` and `coredns-custom` are **migrated into the list** so the abstraction is proven on the existing cases, not only the new one.

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

- **Positive:** the cluster-wide layer becomes declarative + SSOT + scalable; security posture unchanged; existing special-cases (traefik, coredns) folded into one pattern; iris SDD-034c unblocked.
- **Negative / cost:** one new SSOT section + a generalization of the toolkit deploy step; vendored manifests need a version-bump path (a `sync`/`make` target, mirroring `sync-k8s-images`).
- **Follow-up:** D5 addons-project ticketed as a future option; iris validation runbook depends on this landing.
