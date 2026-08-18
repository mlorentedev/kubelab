---
spec: "IDP-031-namespace-resource-governance"
verdict: "PASS"
reviewed_sha: "5d4cf9784cfc3e4e656722174daef6d1746ed709"
reviewer: "nan/deepseek-v4-flash"
date: "2026-08-17"
---

## Adversarial review

**Scope**: IDP-031-namespace-resource-governance (namespace ResourceQuota + LimitRange on `kubelab`)
**Sources**: `specs/IDP-031-namespace-resource-governance/{proposal,tasks,verification,features}.json`; implementation commits `0b1bcee` (#940, LimitRange), `93cffd6` (#1037, quota + surge), `5168384` (#1053, prod), `8bcbb3f` (#1064, ordering evidence), `571e0f9` (#948, RBAC preflight); live clusters staging + prod; rendered kustomize output for both overlays.

### Spec and task alignment

- All six acceptance criteria are covered by at least one named test or a documented one-time measurement. AC1/AC2/AC3/AC4 have permanent pytest tests in `tests/infra/test_k3s.py` (`TestNamespaceGovernance`); AC5 is a one-time surge measurement (documented in `verification.md`, ongoing signal deferred to #918); AC6 is verified per-pod against both live clusters.
- All tasks ticked `[x]` with dated evidence. Every tick maps to a commit hash or an observed run — no `[x]` without diff evidence found.
- Scope discipline holds: the diff touches only `governance/{limitrange,resourcequota}.yaml`, `base/kustomization.yaml`, the test suite, and the spec's own docs. `kube-system-limitrange.yaml` in the same directory is OBS-009 (#1051), a separate spec — its presence here is a sibling artifact, not scope creep.
- No `[AGENT-DRAFT]` / `[AGENT-SUGGESTION]` markers remain in `proposal.md`, `tasks.md`, `verification.md`, or `features.json`.
- `features.json` entries are all `state: "pending"` with empty `evidence` — correct per the pass-state gating rule (only the harness may set `passing`).

### What I ran (evidence, not assertions)

- `make test-infra` equivalent against **live staging**: `poetry run pytest tests/infra/test_k3s.py -m infra --env staging` → **11 passed** in 1.47s. All four IDP-031 tests green individually.
- Live cluster state (staging): quota `hard: requests.memory=4Gi / limits.memory=7Gi`, `used: 2272Mi / 4736Mi`; LimitRange `default 256Mi / defaultRequest 128Mi`; `apprise` and `crowdsec` pods `Running` with initContainers reporting `128Mi/256Mi`. Prod reachable, same quota values (`2400Mi/4Gi`, `4992Mi/7Gi` per verification.md, spot-checked consistency of hard values).
- Rendered kustomize output for **both overlays**: `ResourceQuota` emitted at order position 1, `LimitRange` at 3130 (staging) / 3195 (prod) — the legacy kind-ordering claim in proposal.md → Risks is empirically confirmed. The `argocd.argoproj.io/sync-wave: "-1"` annotation is present on the rendered LimitRange in both.
- **Mutation testing** (each reverted; working tree clean): (a) changed `EXPECTED_QUOTA_LIMITS_MEMORY` 7Gi→8Gi → `test_resourcequota_memory_ceiling` FAILED against live cluster; (b) changed rejection assertion `"memory" in stderr` → `"cpu"` → `test_pod_exceeding_quota_is_rejected` FAILED, proving the test checks the error content, not just failure; (c) changed `EXPECTED_DEFAULT_REQUEST_MEMORY` 128Mi→999Mi → defaulting test FAILED. All three mutations produced the expected failures — the tests are non-vacuous.
- Admission chain spot-checks via `kubectl create --dry-run=server`: a resources-less pod is defaulted to `128Mi/256Mi` (LimitRanger); a pod with `limits.memory: 8Gi` is rejected with `exceeded quota: kubelab-quota, requested: limits.memory=8Gi,requests.memory=8Gi, used: …, limited: limits.memory=7Gi,requests.memory=4Gi` — the rejection names the exceeded resource. A pod with a limit but no request is defaulted to `request=limit` **by the API server itself** (verified in `default` and `kube-system` namespaces, where the LimitRange values differ) — the LimitRange's `defaultRequest` is skipped in that case.
- **Pre-existing defect found during work** (documented in tasks.md and verification.md): `tests/test_monitoring_integration.py` races on a fixed Docker container name under concurrent sessions (#1038). Not in this spec's file scope; the CI full-suite pass is the correct evidence for the remaining 4 tests.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec artifacts | `features.json` f5 verification only exercises the `rollout restart` half of AC5 ("full deploy **followed by** rollout restart"). The deploy half — where an admission rejection would actually surface — is not in the executable command. AC5 itself was exercised manually on staging (0 Pending, peak 6272Mi/7168Mi, exact match to predicted arithmetic), so the criterion is proven; the machine-readable verification is narrower than the criterion it claims to cover. | Read of `features.json` f5 `verification` vs proposal.md AC5 text; `verification.md` calls AC5 "one-time measurement, no permanent test" | UNTESTED (f5 has no named test; it is a manual/rollout-restart command) | spec artifacts (features.json) |
| Minor | REAL | spec artifacts | The pre-flight rationale in tasks.md claims a container declaring a limit below the 128Mi `defaultRequest` would be rejected (LimitRange injects request, request > limit fails). This is wrong: Kubernetes' own pod-defaulting sets `request = limit` for a container that declares a limit but no request, and that happens **before** LimitRanger runs, so `defaultRequest` is never applied to such containers. Verified empirically: `limits.memory: 512Mi` → returned pod has `requests.memory: 512Mi` in `kubelab`; `limits.memory: 64Mi` → `requests.memory: 64Mi` in `kube-system` (different LimitRange values, same result). No practical impact — the pre-flight measured 0 containers in that category on both clusters — but the documented risk model is factually incorrect and would mislead a future value change. | Live admission chain experiments (both namespaces) | UNTESTED (the "mirror case" is asserted in prose, not as a test) | spec artifacts (tasks.md / proposal.md reasoning) |
| Minor | REAL | spec artifacts / tests | AC3 says "`kubectl describe ns kubelab` reports usage against them", but `test_resourcequota_memory_ceiling` reads `status.hard`/`status.used` from the JSON object instead — a deliberate, well-documented deviation (the `tls: {}` lesson: never trust a rendering, read the object). The criterion's intent (usage reported against hard) is met and the JSON check is strictly stronger. Not a defect; recorded so the spec's literal wording and the code's check stay reconciled. | Read of test docstring + test body | `test_resourcequota_memory_ceiling` (passes) | spec artifacts (proposal.md AC3 wording) |
| Minor | THEORETICAL | code | `test_pod_exceeding_quota_is_rejected` uses 8Gi (above the 7Gi hard cap) so it does not depend on other pods' usage. If the quota were ever **raised** above 8Gi (MET-001 raises the ceiling per proposal Risks), this test would silently stop testing rejection — it would fail with a confusing "was ADMITTED" message, which is at least a loud failure, but the 8Gi constant and the quota value are coupled and only one of them is a named constant. | Read of test body; `EXPECTED_QUOTA_LIMITS_MEMORY` is a constant but the probe's 8Gi is not derived from it | `test_pod_exceeding_quota_is_rejected` (passes today) | tests (derive the probe limit from `EXPECTED_QUOTA_LIMITS_MEMORY` + a margin) |
| Minor | SPECULATIVE | reliability | If a future sync applies the quota but the LimitRange fails to apply (or is deleted), `apprise`/`crowdsec` (and any new resources-less pod) would be rejected at admission until a human notices — the failure mode the whole spec exists to prevent. The mitigation is the sync-wave annotation plus the phased rollout history, both verified; nothing actively *warns* if the LimitRange silently disappears. Ongoing quota-utilization alerting is #918's scope (OBS-010, `quota-watcher`), and the tests would fail loudly on the next test run, so this is a detection-latency gap rather than a silent one. | Cross-read of proposal Risks (ordering) + mitigation (sync-wave) + live creationTimestamps (LimitRange 2026-08-10, quota 2026-08-13, three days apart — direct ordering proof) | `test_unspecified_container_is_defaulted` (would fail if the LimitRange vanished; no test asserts the *quota* without the *LimitRange* present) | vault / spec (surface only; tracked as #918 follow-on) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All six ACs verified against live clusters with non-vacuous, mutation-tested checks; the only defect found is incorrect pre-flight *reasoning* in spec prose, not behavior |
| Verification       | A | Every criterion has reproducible evidence: named tests, live-cluster runs, mutation tests, rendered-manifest checks, and honest one-time measurements with exact numbers |
| Scope              | A | Diff matches proposal exactly; no unrelated changes; sibling OBS-009 artifact correctly identified as separate |
| Reliability        | B | Ordering risk mitigated two ways (sync-wave + phased rollout) and directly proven by creationTimestamps; error paths documented; the "LimitRange silently missing" gap is detection-latency, not silence |
| Maintainability    | A | Constants deliberately duplicated against manifests (anti-`tls: {}` lesson), extensive WHY-comments in YAML and tests, clear naming, no dead code |
| Handoff-readiness  | B | Spec docs updated in-session, lessons captured in `docs/lessons.md` (2026-08-09 LimitRange-rejects-pods entry); promotion-candidate boxes in verification.md remain unchecked (archive-time decision) |

### Verdict
PASS

### Recommended next steps (before archive)
- Before archiving, consider tightening `features.json` f5 to include the deploy half of AC5 (or relabel it as a rollout-restart-only check so the machine-readable contract matches the criterion it maps to).
- Correct the pre-flight "mirror case" reasoning in `tasks.md`/`proposal.md`: a limit-without-request container is defaulted to `request = limit` by the API server, so `defaultRequest` is skipped — the risk that actually exists is quota `requests.memory` being charged at the full limit value, which the pre-flight did not measure (measured 0 containers today, both environments, so no action needed beyond the doc correction).
- Consider deriving the 8Gi probe limit in `test_pod_exceeding_quota_is_rejected` from `EXPECTED_QUOTA_LIMITS_MEMORY` so the test tracks a future ceiling raise (MET-001) instead of silently going stale.
- None of the above blocks archive: all are Minor; the change is safe to archive. `dotf spec archive` is **advisable** in the current state once the (unchecked) promotion candidates in `verification.md` are resolved as part of the archive checklist.
