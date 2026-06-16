---
id: "TOOL-009-cluster-operator-bootstrap-tasks"
type: tasks
status: draft
created: "2026-06-16"
---

# Tasks — TOOL-009-cluster-operator-bootstrap

> TDD order, one task = one focused commit. Implements [ADR-047](../../docs/adr/adr-047-cluster-wide-bootstrap-ssot.md).
> Reorder freely while `draft`; freeze on `implementing`. Worktree: `feat/agent-sandbox-runtime`.

## Setup

- [ ] Bitácora item created (mlorentedev/knowledge#NNN) + spec prefix/ID confirmed by owner
- [ ] ADR-047 reviewed and moved `proposed → accepted`

## Implementation

- [ ] **T1: SSOT schema** — add `cluster_operators:` list to `infra/config/values/common.yaml`
      (`{name, namespace, version, manifest}`), starting with `agent-sandbox` `v0.5.0rc1`. Define the
      vendored-manifest layout `infra/k8s/cluster/<name>/manifest.yaml`. Verification: `toolkit config
      validate` passes; the SSOT parses.
- [ ] **T2: Generalized apply** — replace `_get_traefik_config_path()` in `toolkit/cli/infra.py`
      `k8s_deploy` step 3 with a loop over `cluster_operators`: dry-run then `kubectl apply
      --server-side -f <manifest>` per entry, per-operator logging, stable order. Verification: unit
      test asserts the loop applies every declared operator; `make test` green.
- [ ] **T3: Migrate existing cases** — fold `traefik-config` and `coredns-custom` into
      `cluster_operators`; remove the hardcoded `_get_traefik_config_path()` and the Makefile coredns
      `sed | kubectl apply`. Verification: `toolkit infra k8s deploy --env staging` applies all three;
      no per-component branches remain (grep clean).
- [ ] **T4: Vendor agent-sandbox** — vendor the pinned `v0.5.0rc1` manifest at
      `infra/k8s/cluster/agent-sandbox/manifest.yaml` (CRD v1beta1 + controller + RBAC + namespace).
      Verification: `kubectl apply --server-side --dry-run=server` accepts it on the staging cluster.
- [ ] **T5: Version-bump automation** — `make sync-operators` (or extend `sync-k8s-images`) refreshes
      a vendored manifest from the SSOT-pinned version. Verification: bumping the version in
      `common.yaml` + running the target updates the vendored file deterministically.
- [ ] **T6: Deploy to staging** — `make deploy-k8s ENV=staging`; agent-sandbox controller Ready in
      `agent-sandbox-system`, `sandboxes.agents.x-k8s.io` (v1beta1) served. Verification: `kubectl get
      crd sandboxes.agents.x-k8s.io` + controller rollout complete.
- [ ] **T7: Validate iris SDD-034c** — in the iris repo:
      `KUBECONFIG=~/.kube/kubelab-staging-config go test ./internal/runtime/k8s/ -run TestK8sConformance
      -v`. Verification: conformance passes (Start/Stop/Status/Exec + sidecar) against the real cluster.

## Ordering rationale
T1→T2 (schema before the loop that reads it) → T3 (migrate once the loop works) → T4 (vendor the new
operator) → T5 (automate refresh) → T6 (deploy) → T7 (downstream iris validation, the original goal).

## Closing
- [ ] `features.json` entries all have non-vacuous verification commands (pass-state set by harness, not agent)
- [ ] `verification.md` filled in
- [ ] No Argo CD RBAC widened (ADR-047 D1 invariant holds)
- [ ] PR opened referencing this spec + ADR-047; iris SDD-034c open thread closed
