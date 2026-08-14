---
tags: [spec, verification, templates]
created: "2026-08-09"
---

# Verification - IDP-031-namespace-resource-governance

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] Criterion 1 (LimitRange defaults exist for every quota-constrained dimension) -> commit `0b1bcee` (#940) / test `test_limitrange_defaults_memory`
- [x] Criterion 2 (unspecified container is admitted and defaulted) -> commit `0b1bcee` (#940) / test `test_unspecified_container_is_defaulted`
- [x] Criterion 3 (ResourceQuota constrains requests/limits.memory, `describe ns` reports usage) -> commit `e25e811` / test `test_resourcequota_memory_ceiling`
- [x] Criterion 4 (workload exceeding ceiling is rejected, error names the resource) -> commit `e25e811` / test `test_pod_exceeding_quota_is_rejected`
- [x] Criterion 5 (surge case: full deploy + rollout restart, no pod Pending on quota) -> exercised 2026-08-12, staging (see Test status below); no permanent test — one-time measurement, ongoing signal is #918's scope
- [x] Criterion 6 (apprise/crowdsec admitted and Running with quota active, both environments) -> staging proven 2026-08-12; prod proven 2026-08-14 (see Decisions below — required an unplanned restart, initContainers now report `128Mi`/`256Mi`, `Burstable`, `Running`)

## Test status

- `make test-infra ENV=staging` -> 29 passed, 1 skipped (pre-existing, unrelated DNS skip), 2026-08-12
- `make test-infra ENV=prod` -> 27 passed, 6 skipped (pre-existing, unrelated), 0 failed, 2026-08-14 — run on a branch forked fresh from `origin/master` (post both #1037 and #1051 merges), so this single run is also the prod evidence for OBS-009's `TestKubeSystemGovernance` (see that spec's verification.md)
- `make lint` -> All checks passed, 62 files already formatted, 2026-08-14
- `make type` -> Success: no issues found in 61 source files, 2026-08-14
- `make test` (local, partial: 468 of the repo's full suite) -> 468 passed with `tests/test_monitoring_integration.py` deselected. That file's 4 tests error intermittently under this session's concurrent worktree load: its fixture uses a fixed Docker container name (`kubelab-test-kuma`) with a `docker rm -f` at both setup and teardown, which races when two sessions on this machine run it at once — a real defect, but pre-existing, untouched by this diff, and outside this lane's file scope (`toolkit/features/monitoring*`/its tests, per lane ownership). Ticketed as #1038 rather than fixed. **The full suite, including those 4 tests, is separately proven green by CI** (`.github/workflows/`), which runs single-tenant on a GitHub-hosted runner where this contention cannot occur — that CI run, not this local one, is the actual full-suite evidence.
- Manual smoke test (surge case, AC5): full `make deploy-k8s ENV=staging` followed by `rollout restart` of all 14 deployments. 0 pods `Pending`, 0 quota-related `FailedCreate` events, all deployments ready within 46s. Peak `requests.memory` used: 3008Mi/4096Mi hard. Peak `limits.memory` used: 6272Mi/7168Mi hard — an exact match to the spec's predicted arithmetic (4.875Gi baseline + 1.25Gi four-deployment surge = 6272Mi). Diagnostic script was scratch-only (not committed); the durable artifact is this measurement, per the project's diagnostic-script convention — ongoing alerting on this signal is #918's scope, not this spec's.
- Prod Phase 4 smoke test, 2026-08-14: `make restart-service SVC=apprise ENV=prod` / `SVC=crowdsec ENV=prod` — both rolled out cleanly, initContainers `seed-config`/`inject-whitelist` went from `{}` to `128Mi`/`256Mi`. `make backup-pvc ENV=prod` (ADR-024) triggered the CronJob's pod spec on demand: admitted, `Succeeded`, `Burstable`, quota `requests.memory: 2400Mi/4Gi` / `limits.memory: 4992Mi/7Gi` at time of run.
- No regressions in existing test suite: yes — all pre-existing `tests/infra/` tests still pass in both environments.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **Re-measured usage before applying the quota (2026-08-12), instead of trusting the 2026-08-09 numbers.** They matched exactly (2.312 Gi requests / 4.875 Gi limits, both environments) once terminal-phase pods were excluded — but the raw `kubectl get pods` sum did NOT match on first pass: prod showed 2.688/6.375 Gi due to three lingering `Succeeded` `pvc-backup-*` Job pods from the last three nightly runs. `ResourceQuota`'s usage controller excludes `Succeeded`/`Failed` pods from compute-resource accounting (`QuotaV1Pod` semantics) — a `kubectl get pods` sum that doesn't filter by phase overcounts against what the quota actually enforces. Worth stating explicitly because it is exactly the kind of measurement gap that produced the original "zero unbounded containers" error this spec's Risks section already documents once (initContainers vs containers) — same failure shape, different omission.
- **RBAC preflight before deploying**, not after hitting `forbidden`: `kubectl auth can-i create resourcequotas -n kubelab --as=system:serviceaccount:kubelab:argocd-manager` confirmed `yes` in both environments before any apply, meaning `make register-spoke` from #948 had already been run. Cheaper than diagnosing a mid-deploy failure per TOOL-029.
- **Phase 4's `apprise`/`crowdsec` "stay Running" check needed a restart that wasn't in the original task text.** `selfHeal` landed the `LimitRange`/`ResourceQuota` in prod automatically, but neither pod had actually restarted since — `Burstable` QoS was visible immediately (proves the *main* container carries a request, since both already had explicit values pre-dating this spec) and was nearly mistaken for proof the *initContainers* were defaulted too. They weren't: `spec.initContainers[*].resources` read `{}` until an explicit `make restart-service` picked up the `LimitRange` defaults. Same failure shape as the two measurement gaps already logged in this file and in OBS-009's verification.md — a proxy signal (QoS class) standing in for the thing actually being claimed (initContainer defaulting), caught by reading the underlying object instead of the derived field.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
