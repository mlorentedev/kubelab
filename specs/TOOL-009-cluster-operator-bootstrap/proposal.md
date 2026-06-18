---
id: "TOOL-009-cluster-operator-bootstrap"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-06-16"
issue: "mlorentedev/knowledge#118"
tags: [spec, proposal, toolkit, k8s, bootstrap, operators, ssot, argocd]
template_version: "1.0"
---

# TOOL-009-cluster-operator-bootstrap

> Prefix provisional — `TOOL-` (toolkit capability; the change lives in `toolkit/cli/infra.py`).
> Could be `SSOT-`/`INFRA-` if you prefer; owner to confirm. Implements [ADR-047](../../docs/adr/adr-047-cluster-wide-bootstrap-ssot.md).

## Why

kubelab applies cluster-scoped resources (CRDs, ClusterRoles, controllers in non-`kubelab`
namespaces) **outside** the Argo CD overlay, because the Argo CD spoke RBAC is deliberately
least-privilege (manages `kubelab` only; cluster-wide is read-only — ADR-041). Today that
"outside-Kustomize" apply is **two hardcoded special-cases**: `traefik-config.yaml` via
`_get_traefik_config_path()` in `toolkit/cli/infra.py`, and `coredns-custom` via a `sed | kubectl
apply` in the Makefile. There is no shared, declarative mechanism.

Integrating `kubernetes-sigs/agent-sandbox` (the runtime substrate for iris SDD-034c) is the **third**
cluster-wide component — the point where the special-case approach must become a real pattern. Doing
it as a third hardcode would feed an antipattern and break the project's SSOT/declarative principle
(ADR-036). This spec makes the cluster-wide bootstrap layer **SSOT-declarative and automated**, per
ADR-047, *without* changing the (correct, least-privilege) architecture.

## What

> **Premise correction (2026-06-17 code + vault audit).** The original draft said "two static
> special-cases (traefik + coredns)". Reality: the `_get_traefik_config_path()` branch is **dead code**
> (its file was removed in ADR-020 Ph3; HelmChartConfig is now Ansible-managed), and `coredns-custom`
> lives in `make deploy-external` with a `RESOLVE_RPI4_TAILSCALE_IP` placeholder resolved at deploy time
> via MagicDNS (ADR-025). The same `RESOLVE_*` pattern recurs inline in **3** Makefile sites. So this
> spec kills *inline shell*, not "static special-cases".

1. **SSOT declaration** — add a top-level `cluster_bootstrap:` list to `infra/config/values/common.yaml`,
   each entry `{ name, namespace, manifest }` + optional `{ version, render, optional }` (vendored,
   version-pinned manifests under `infra/k8s/cluster/<name>/`). `version` only for *versioned* operators;
   `render` is a `RESOLVE_*`→MagicDNS-name map; `optional` skips on unresolvable target. Key named
   `cluster_bootstrap` (owner decision) because the list mixes operators + cluster config.
2. **Render primitive** — `render_and_apply(manifest, render_map, kubeconfig, *, optional, server_side)`:
   resolve `RESOLVE_*` via MagicDNS, substitute in-memory, `--dry-run=server`, apply. Idempotent,
   order-stable, per-operator logging. `toolkit infra k8s deploy` step 3 loops `cluster_bootstrap`
   through it (replacing the dead `_get_traefik_config_path()`, which is **deleted**).
3. **Migrate all 3 inline sites** — coredns/rpi4 (`Makefile:473`), uptime-kuma/rpi3 (`Makefile:469`),
   argocd/aws1 (`Makefile:432`) move off inline `dig | sed | kubectl` onto the render primitive
   (owner decision: all 3 in this PR). The Makefile keeps no deploy-time substitution shell.
4. **agent-sandbox as first operator** — vendor `agent-sandbox` `v0.5.0rc1` (`agents.x-k8s.io/v1beta1`,
   image `registry.k8s.io/agent-sandbox/agent-sandbox-controller:v0.5.0rc1`); declare it in the list.
5. **Version-bump path** — a `make sync-operators` (or extend `sync-k8s-images`) target that refreshes
   the vendored manifest from the SSOT-pinned version, mirroring how image tags are synced.
6. **Unblock iris SDD-034c** — after `make deploy-k8s ENV=staging`, the agent-sandbox controller is
   live and `KUBECONFIG=~/.kube/kubelab-staging-config go test ./internal/runtime/k8s/ -run
   TestK8sConformance` (in the iris repo) exercises the real Start/Stop/Status/Exec + sidecar path.

## Out of scope

- **Full-GitOps `cluster-addons` Argo CD AppProject** (scoped-elevated RBAC + sync waves) — ADR-047 D5
  descopes this as a future option; not built here.
- Granting Argo CD any cluster-write RBAC — explicitly rejected (ADR-047 D1).
- iris-side code — SDD-034c is merged; this spec only provides the substrate to validate it.
- Helm-chart packaging of agent-sandbox — vendored manifest is sufficient; revisit if a chart is
  needed later.

## Risks / open questions

- **[OPEN — owner]** Spec prefix/ID (`TOOL-` vs `SSOT-`/`INFRA-`) and the bitácora `issue:` number.
- **[OPEN — design]** `v0.5.0rc1` is not a valid Go-semver tag, so the **iris** module dep stays on
  `agent-sandbox@main` (a v1beta1 pseudo-version); the **cluster** runs `v0.5.0rc1`. Both are v1beta1
  → wire-compatible. Re-pin iris to a real tag once upstream ships a semver v1beta1 release.
- **[OPEN — design]** Namespace for iris agents: conformance uses `default`; consider a dedicated
  `iris-agents` namespace for the permanent integration.
- **[RESOLVED]** Does this need ArgoCD changes? No — cluster-wide stays outside Argo CD by design.
- **[RESOLVED]** Does the overlay break the operator? Yes if included — hence it is applied outside the
  overlay (the whole point of this spec).

## Acceptance criteria

- [ ] `cluster_bootstrap:` exists in `common.yaml` with `agent-sandbox` (versioned) and `coredns-custom`
      (render + optional) entries; versions/render maps are the SSOT.
- [ ] `toolkit infra k8s deploy --env staging` applies every `cluster_bootstrap` entry (server-side),
      dry-run-validated, with the dead `_get_traefik_config_path()` removed and no `RESOLVE_*`
      substitution shell left in the Makefile (all 3 sites on the render primitive).
- [ ] agent-sandbox `sandboxes.agents.x-k8s.io` CRD (v1beta1) + controller are Ready in
      `agent-sandbox-system` after `make deploy-k8s ENV=staging`.
- [ ] `make sync-operators` refreshes a vendored manifest from the SSOT version (versioned entries only).
- [ ] iris `go test ./internal/runtime/k8s/ -run TestK8sConformance` passes against staging
      (Start/Stop/Status/Exec + sidecar) — the SDD-034c validation.
- [ ] Toolkit unit tests cover the render primitive + the `cluster_bootstrap` apply loop and pass via `make test`.

## References

- ADR: [ADR-047](../../docs/adr/adr-047-cluster-wide-bootstrap-ssot.md) (this spec implements it).
- Related ADRs: ADR-021 (Helm/Kustomize split), ADR-036 (shared-infra SSOT), ADR-041 (least-privilege),
  ADR-046 (GitOps delivery).
- Code: `toolkit/cli/infra.py` (`k8s_deploy`, `_get_traefik_config_path`), `Makefile` (coredns apply,
  `sync-k8s-images`), `infra/config/values/common.yaml`.
- Downstream consumer: iris SDD-034c (`internal/runtime/k8s`), pinned to `agent-sandbox@main` (v1beta1).
- Upstream: `kubernetes-sigs/agent-sandbox` v0.5.0rc1 manifest (CRD v1beta1 + controller image).
