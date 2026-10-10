---
tags: [spec, verification]
created: "2026-10-10"
---

# Verification - TOOL-009-cluster-operator-bootstrap

Written on 2026-10-10 during DEBT-019 (#2034): the implementation merged on 2026-06-18 in #676, and this file was never filled in. Every command below was re-run from master on 2026-10-10.

## Evidence

- [x] AC1 (`cluster_bootstrap:` SSOT with `agent-sandbox` and `coredns-custom`) -> #676 / features f1: `toolkit config validate` passes and both entries parse. The list has since grown to three (`kube-system-limitrange`, OBS-009).
- [x] AC2 (deploy applies every entry; dead `_get_traefik_config_path()` removed; no `RESOLVE_*` substitution shell in the Makefile) -> #676 / f2: the grep for `_get_traefik_config_path` in `toolkit/` and for `s/RESOLVE_` in the Makefile are both clean; every remaining render site calls `toolkit infra k8s render-apply` (`argocd-repoint`, `RESOLVE_GCP1_TAILSCALE_IP`); `deploy-external` is gone (`Makefile:716`). Tests: `tests/test_k8s_render.py`, `tests/test_cluster_bootstrap.py`, 25 passed.
- [x] AC3 (agent-sandbox CRD v1beta1 and controller Ready) -> f5: `sandboxes.agents.x-k8s.io` serves `v1beta1` and `agent-sandbox-controller` is rolled out, in staging (114 days old) and in prod (57 days).
- [x] AC4 (`make sync-operators` refreshes the vendored manifest from the SSOT version) -> f4: the target runs and `git diff --exit-code infra/k8s/cluster/` is clean, so the vendored file matches the pinned `v0.5.0rc1`.
- [ ] AC5 (iris `TestK8sConformance` against staging) -> **ticketed in the consumer: mlorentedev/iris#30**, open since 2026-06-18. Re-run on 2026-10-10 at iris `748d2f1`: every Start-based subtest fails with `metadata.labels: Invalid value: "<64 hex>": must be no more than 63 characters`. The API server validated the `Sandbox` against the CRD this spec installed and refused iris's own `iris.spec-hash` label, so the cluster side this spec owns is proven by the same run, and the conformance is blocked on iris's adapter.
- [x] AC6 (unit tests for the render primitive and the loop) -> `tests/test_k8s_render.py`, `tests/test_cluster_bootstrap.py`, 25 passed; both run in `make test`.

## Test status

- `pytest tests/test_k8s_render.py tests/test_cluster_bootstrap.py` -> 25 passed (2026-10-10).
- Live, read-only, 2026-10-10: CRD versions and controller rollout status in staging and prod.
- No regressions in existing test suite: yes.

## Decisions made during implementation

- **f2's verification command was vacuous.** It ran `pytest toolkit -k 'render or cluster_bootstrap'`, but the tests live in `tests/`, so pytest collected nothing and exited 5. A harness reading the exit code would have reported it failing; one reading output would have seen no tests. Corrected in `features.json` to name the two test files.
- **`_apply_cluster_bootstrap` is not impersonated** as Argo CD's service account, by design: CRDs and cluster-scoped objects need operator privilege, and the spoke's RBAC is not widened for them (ADR-047 D1; CLAUDE.md, TOOL-029).

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? no: the one correction here (a vacuous verification command) is the shape lesson-545 records for fakes, and this file records the instance.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? yes: docs/adr/adr-047-cluster-wide-bootstrap-ssot.md
- [x] New pattern candidate for `00_meta/patterns/`? no: the bootstrap layer is specific to this fleet.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved to `specs/archive/`
- [ ] Bitácora ticket closed with PR link (ADR-018)
