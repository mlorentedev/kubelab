---
tags: [spec, verification, templates]
created: "2026-08-13"
---

# Verification - OBS-009-kube-system-limitrange

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] Criterion 1 (LimitRange exists, cluster_bootstrap, absent from kustomization) -> commit `d74bb82` / test `TestKubeSystemGovernance::test_limitrange_defaults_memory`
- [x] Criterion 2 (unspecified container admitted and defaulted) -> commit `7d2e356` / test `TestKubeSystemGovernance::test_unspecified_container_is_defaulted`
- [x] Criterion 3 (zero unbounded Running containers, non-BestEffort QoS after restart) -> commit `5d9cb49` / test `TestKubeSystemGovernance::test_no_unbounded_containers_after_restart` — staging proven 2026-08-13; prod proven 2026-08-14 (Part 3, post-merge)
- [x] Criterion 4 (restart is do-no-harm, ingress keeps serving) -> `make test-e2e ENV=staging`, 71 passed / 12 skipped (pre-existing) / 0 failed, 2026-08-13

## Test status

- `make test-infra ENV=staging` -> 30 passed, 1 skipped (pre-existing, unrelated DNS skip), 2026-08-13
- `make test-e2e ENV=staging` -> 71 passed, 12 skipped, 0 failed, 2026-08-13 (run immediately after restarting traefik/svclb/local-path-provisioner/metrics-server)
- `make lint` -> All checks passed, 62 files already formatted
- `make type` -> Success: no issues found in 61 source files
- `poetry run pytest --deselect tests/test_monitoring_integration.py --no-cov` (full suite minus the pre-existing, out-of-lane flake ticketed as #1038) -> 486 passed
- Manual smoke test: `make bootstrap-k8s ENV=staging` applied the LimitRange (dry-run validated first); restarted `traefik`, `svclb-traefik-ca274381`, `local-path-provisioner`, `metrics-server`; confirmed via `kubectl get pods -n kube-system -o json` that every Running container now carries `requests.memory: 64Mi` / `limits.memory: 384Mi` (or its own pre-existing, already-sufficient values for `coredns`) and QoS class `Burstable`.
- `make test-infra ENV=prod` -> 27 passed, 6 skipped (pre-existing), 0 failed, 2026-08-14 (Part 3) — includes all 3 `TestKubeSystemGovernance` cases; run on a branch forked fresh from `origin/master` post-merge, so this single run is also the prod evidence cited in IDP-031's verification.md
- Prod smoke test (Part 3), 2026-08-14: `make bootstrap-k8s ENV=prod` applied the LimitRange; prod's svclb DaemonSet suffix (`svclb-traefik-416bf32a`) differs from staging's (`ca274381`), confirming the dynamic-name risk documented in proposal.md is real rather than a staging artifact. Restarted `traefik`/`local-path-provisioner`/`metrics-server` via `make restart-service`, and the DaemonSet via `kubectl rollout restart` (no toolkit target covers DaemonSets — deployments only). Post-restart: 0 unbounded Running containers, 0 BestEffort Running pods, verified via `kubectl get pods -n kube-system -o json`.
- No regressions in existing test suite: yes
- Re-verified 2026-10-10 from master: `make test-infra ENV=prod` -> 71 passed, 1 skipped (`test_local_dns_entries`, unrelated); all three `TestKubeSystemGovernance` cases pass in prod.

## Adversarial review findings

`review.md` (2026-10-10, PASS-WITH-GAPS, one Major, no Blocker). Each finding's disposition:

| # | Finding | Disposition |
|---|---|---|
| 1 (Major) | Nothing guards the invariant that the manifest is never a Kustomize resource; the reviewer listed it in the base and the full suite passed | Fixed in the archive PR: `test_a_bootstrap_manifest_is_never_a_kustomize_resource` in `tests/test_cluster_bootstrap.py`, parametrized over every `cluster_bootstrap` entry, plus `test_the_kustomize_scan_reaches_the_base` so it cannot pass over nothing. `make mutate` listing the file, and separately its `governance` directory, in the base `resources:`: both red. |
| 2 | A kube-system container requesting more than 384Mi with no limit would be rejected at admission, and no test sees a Pending workload | Ticketed: #2163 (OBS-032). Re-measured by the review on 2026-10-10: no such container in either cluster. |
| 3 | `test_no_unbounded_containers_after_restart` ignored `initContainers` | Fixed in the archive PR: the test reads `initContainers` too. Passes against prod and staging on 2026-10-10 (there are none today). |
| Q | 384Mi was sized from Traefik at rest, never under load | Tracked by #1052 (OBS-020, Traefik's explicit `resources`), which the proposal already names. |

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **`metrics-server` was missing from the original restart plan.** Both `proposal.md` and the first draft of `tasks.md` Part 2 listed only `traefik`, `svclb-traefik`, and `local-path-provisioner` as the affected workloads — despite `metrics-server`'s missing limit being named explicitly in the parent ticket (#924)'s own measurement table. The gap wasn't caught by re-reading the proposal; it was caught by the `test_no_unbounded_containers_after_restart` assertion itself failing (well, would have failed — it was written and passed only after the correction, so more precisely: caught by manually inspecting `kubectl get pods -o json` before writing the assertion, per this session's practice of measuring rather than trusting a plan). Corrected in both spec files and the restart itself before the assertion was ever written, so the test was never actually run red for this specific gap — worth recording anyway since it's the same failure shape as IDP-031's `spec.containers`-only measurement bug: trusting a list instead of re-deriving it from the live cluster.
- **The `svclb` DaemonSet name carries a dynamic suffix** (`svclb-traefik-ca274381`, not the literal `svclb-traefik` named in the original ticket and this spec's early drafts) — generated by K3s's service-lb controller, not a fixed name. `tasks.md` corrected to say "resolve with `kubectl get daemonset -n kube-system` first" rather than hardcoding it, since the suffix is cluster-instance-specific and would differ in prod.
- **Followed the IDP-031 precedent of re-measuring rather than trusting the ticket's numbers**: `kubectl top pod -n kube-system` on both clusters, 2026-08-13, confirmed Traefik's real footprint (149Mi staging / 170Mi prod at rest) before freezing the `default.memory: 384Mi` value — this is the number that made the request/limit asymmetry (64Mi/384Mi, not a uniform tier) a measured decision rather than a guess.
- **`tasks.md` Part 1 was done but never ticked** — the work landed (commits `d74bb82`/`7d2e356`, staging proven) but the checkboxes were left unchecked, so the file stopped matching reality. Caught while closing out Part 3, corrected with dated evidence rather than left as a stale artifact.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons.md`? no: the two corrections recorded above (metrics-server missing from the plan, the svclb suffix) are the measure-don't-trust-the-list shape that lesson-305 and lesson-003 already record for IDP-031.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the LimitRange extends IDP-031's namespace governance to kube-system through the existing `cluster_bootstrap` layer (ADR-047); no decision is reversed.
- [x] New pattern candidate for `00_meta/patterns/`? no: kube-system governance is specific to this K3s fleet.

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] Promotions above executed (if any)
