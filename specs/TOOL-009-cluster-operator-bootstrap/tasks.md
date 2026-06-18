---
id: "TOOL-009-cluster-operator-bootstrap-tasks"
type: tasks
status: implementing # frozen on implementing (2026-06-17)
created: "2026-06-16"
---

# Tasks — TOOL-009-cluster-operator-bootstrap

> TDD order, one task = one focused commit. Implements [ADR-047](../../docs/adr/adr-047-cluster-wide-bootstrap-ssot.md).
> **Frozen on `implementing` (2026-06-17)** after a code + vault audit corrected the ADR premise
> (traefik branch is dead code; coredns lives in `deploy-external` with MagicDNS templating; the
> `RESOLVE_*` pattern recurs in 3 Makefile sites). Worktree: `feat/agent-sandbox-runtime`.

## Setup

- [x] Spec prefix/ID confirmed by owner: **TOOL-009** (toolkit capability) ✓ 2026-06-17
- [x] SSOT key name confirmed by owner: **`cluster_bootstrap`** ✓ 2026-06-17
- [x] Render-migration scope confirmed by owner: **all 3 sites** ✓ 2026-06-17
- [x] ADR-047 reviewed and moved `proposed → accepted` ✓ 2026-06-17
- [x] Bitácora item created (mlorentedev/knowledge#118) ✓ 2026-06-17

## Implementation

> **Status 2026-06-17:** T1–T8 done + validated. Substrate live on staging via
> `make bootstrap-k8s ENV=staging`: `sandboxes.agents.x-k8s.io` (v1beta1) served,
> `agent-sandbox-controller` 1/1 Running. Toolkit: 25 render/cluster_bootstrap unit
> tests green (k8s_render 100% cov), full suite 210 passed. **T9 BLOCKED by an
> iris-side bug** (out of TOOL-009 scope): `iris internal/runtime/k8s/k8s.go:158`
> stamps a 64-char spec hash as the `iris.spec-hash` label value — K8s caps label
> values at 63 chars, so the API rejects every `Sandbox` create. The substrate is
> proven (adapter connects; `Status_on_unknown_handle` subtest passes); conformance
> needs the iris fix (truncate the hash for the label, consistently at write + drift
> compare). **Filed as `mlorentedev/iris#30`.**

- [x] **T1: SSOT schema** — add top-level `cluster_bootstrap:` list to `infra/config/values/common.yaml`
      (near `k3s:`). Entry shape `{name, namespace, manifest}` + optional `{version, render, optional}`.
      Seed with `agent-sandbox` (`version: v0.5.0rc1`, server-side) and `coredns-custom`
      (`render: {RESOLVE_RPI4_TAILSCALE_IP: rpi4.kubelab.internal}`, `optional: true`). Define the
      vendored layout `infra/k8s/cluster/<name>/manifest.yaml`. Verification: `toolkit config validate`
      passes; SSOT parses; the 3 expected names present.
- [ ] **T2: render primitive** — `render_and_apply(manifest, render_map, kubeconfig, *, optional,
      server_side)` in the toolkit: resolve each `RESOLVE_*` via MagicDNS, substitute in-memory,
      `--dry-run=server`, then apply. Verification: unit tests cover substitution, skip-if-optional-
      unresolvable, dry-run-before-apply, stable order; `make test` green.
- [ ] **T3: cluster_bootstrap loop** — replace `_get_traefik_config_path()` (DEAD CODE — target file
      removed in ADR-020 Ph3, HelmChartConfig now Ansible-managed) in `infra.py` `k8s_deploy` step 3
      *and* `k8s_dry_run` with a loop over `cluster_bootstrap` via the render primitive, per-operator
      logging, stable order. Verification: unit test asserts the loop applies every declared entry; no
      `_get_traefik_config_path` left (grep clean); `make test` green.
- [ ] **T4: migrate 3 call-sites** — move coredns/rpi4 (`Makefile:473`), uptime-kuma/rpi3
      (`Makefile:469`), argocd/aws1 (`Makefile:432`) off inline `dig | sed | kubectl` onto the render
      primitive. coredns is applied via the `cluster_bootstrap` loop (T3); rpi3/aws1 EndpointSlices via
      a small toolkit command each. Verification: no `RESOLVE_*`-substitution shell remains in the
      Makefile (grep clean); `deploy-external` / `_deploy-argocd-helm` call the toolkit.
- [ ] **T5: vendor agent-sandbox** — vendor the pinned `v0.5.0rc1` manifest at
      `infra/k8s/cluster/agent-sandbox/manifest.yaml` (CRD `agents.x-k8s.io/v1beta1` + controller +
      RBAC + `agent-sandbox-system` namespace). Verification: `kubectl apply --dry-run=server` accepts
      it on the staging cluster.
- [ ] **T6: sync automation** — `make sync-operators` (toolkit) refreshes vendored manifests for
      `cluster_bootstrap` entries that have a `version` (config entries like coredns are skipped).
      Verification: bumping the version in `common.yaml` + running the target updates the vendored file
      deterministically.
- [ ] **T7: doc-drift + premise fix** — correct CLAUDE.md (coredns "applied via deploy-k8s"),
      `docs/lessons.md:1545`, and the `coredns-custom.yaml` header to match reality after T3/T4
      (coredns now in the `deploy-k8s` bootstrap loop). ADR-047 + this spec already reflect the
      corrected premise. Verification: grep shows no remaining "applied via make deploy-k8s" claim that
      contradicts code.
- [ ] **T8: deploy to staging** — `make deploy-k8s ENV=staging`; agent-sandbox controller Ready in
      `agent-sandbox-system`, `sandboxes.agents.x-k8s.io` (v1beta1) served. Verification: `kubectl get
      crd sandboxes.agents.x-k8s.io` + controller rollout complete.
- [ ] **T9: validate iris SDD-034c** — in the iris repo:
      `KUBECONFIG=~/.kube/kubelab-staging-config go test ./internal/runtime/k8s/ -run TestK8sConformance
      -v`. Verification: conformance passes (Start/Stop/Status/Exec + sidecar) against the real cluster.

## Ordering rationale
T1 (schema) → T2 (primitive the loop/sites consume) → T3 (loop + delete dead code) → T4 (migrate the
3 inline sites) → T5 (vendor the operator) → T6 (automate refresh) → T7 (doc drift) → T8 (deploy) →
T9 (downstream iris validation, the original goal).

## Closing
- [ ] `features.json` entries all have non-vacuous verification commands (pass-state set by harness, not agent)
- [ ] `verification.md` filled in
- [ ] No Argo CD RBAC widened (ADR-047 D1 invariant holds)
- [ ] PR opened referencing this spec + ADR-047; iris SDD-034c open thread closed
