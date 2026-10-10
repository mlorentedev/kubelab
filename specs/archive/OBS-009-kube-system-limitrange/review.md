---
spec: "OBS-009-kube-system-limitrange"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "a625f30e86780803ebd5293028a84d69b866526f"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-10"
---

## Adversarial review

**Scope**: OBS-009-kube-system-limitrange, diff `02e8d15b3e592ba2dab87e4e49b339b49c111bc0...HEAD` (the base the launcher resolved — parent of the spec's squash commit `3b3f194a`, PR #1051 — used verbatim, not substituted).

**Sources**: `specs/OBS-009-kube-system-limitrange/{proposal,tasks,verification}.md`, `features.json`; implementation in `infra/k8s/base/governance/kube-system-limitrange.yaml`, the `cluster_bootstrap` entry in `infra/config/values/common.yaml:603`, `tests/infra/test_k3s.py::TestKubeSystemGovernance`.

**Scope note (whole-change reading)**: the stated range spans 646 commits because this branch carries master history from #1051 forward (up to #2151) plus the `wip: OBS-009/010 verification` head. Per-file `git log 02e8d15..HEAD` shows every OBS-009 artifact (manifest, spec files, `features.json`, the `common.yaml` entry) was touched **only** by OBS-009's own commits (`3b3f194a`, `d6d17894`, `a625f30e`); `tests/infra/test_k3s.py` was additionally touched by `eedaf4d6` (#1141), but only in the IDP-031 quota-probe section, and the full suite passes at HEAD. No cross-spec interaction defect found.

### Spec and task alignment

- **AC1 (LimitRange exists, cluster_bootstrap, absent from kustomization)** — manifest carries exactly `defaultRequest.memory: 64Mi` / `default.memory: 384Mi`, `type: Container`, `namespace: kube-system`; `common.yaml` entry present with no `version`/`render` and `optional` defaulting to `False` (`BootstrapEntry.from_dict`, matching the proposal's `optional: false`); `infra/k8s/base/kustomization.yaml` confirmed to carry `namespace: kubelab` and **not** list the manifest. Verified live by the reviewer: `TestKubeSystemGovernance` 3/3 passed against **staging and prod**. All cited commits (`7d2e356`, `d74bb82`, `5d9cb49`, `d6d17894`, `3b3f194a`) exist.
- **AC2 (unspecified pod admitted + defaulted)** — `test_unspecified_container_is_defaulted` uses `--dry-run=server` (read-only, safe against prod), asserts both injected values against independent constants. Live pass both envs. **Mutation red-proof by reviewer**: changing `EXPECTED_KUBE_SYSTEM_DEFAULT_LIMIT_MEMORY` to `512Mi` made the test fail (`tests/infra/test_k3s.py:363 AssertionError`), so it compares against the cluster, not itself; reverted.
- **AC3 (zero unbounded Running containers, no BestEffort)** — live pass both envs. Reviewer's independent `kubectl get pods -n kube-system -o json` dump (2026-10-10): every Running container in staging and prod carries `requests.memory` and `limits.memory` (traefik/svclb/local-path/metrics-server at 64Mi/384Mi, coredns on its own 70Mi/170Mi), all pods `Burstable`, zero containers in the request-without-limit danger category.
- **AC4 (restart is do-no-harm)** — evidence is the historical `make test-e2e ENV=staging` run (71 passed / 12 skipped / 0 failed, 2026-08-13, immediately after the restart). **Not re-run by this review** — the criterion is about the restart moment, which is past; marked UNVERIFIED by this round.
- **tasks.md** — all boxes `[x]`, each with dated commit evidence; verified the cited commits are reachable. **features.json** — 4 entries, one per AC, non-vacuous commands (f1 includes the kustomization grep); all `state: pending` / empty `evidence`, correct per the pass-state gating rule (the harness, not the agent, sets `passing`).
- No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain (the `tasks.md` mention is prose describing their removal; an archived sibling, SEC-004, carries the identical phrasing and archived fine).

**Evidence produced this round**: full static suite at HEAD `4410 passed, 16 skipped, 162 deselected, 2 xfailed` (397s); `make lint` and `make type` clean; `tests/test_cluster_bootstrap.py` + `tests/test_orphan_manifests.py` 10 passed; `TestKubeSystemGovernance` 3/3 on staging and prod; two mutation experiments (both reverted, tree clean apart from launcher `review-request.json` files).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Major | THEORETICAL | tests / process | The spec's explicitly critical invariant — "never register this manifest in `infra/k8s/base/kustomization.yaml`" (manifest header calls it *the one mistake that silently defeats the whole spec*) — has **no automated guard**. Registering it there would rewrite the object into a second `kubelab` LimitRange and silently leave `kube-system` unbounded, and nothing in CI would notice. | Mutation by reviewer: added `- governance/kube-system-limitrange.yaml` to the base `resources:` and ran the **full static suite → 4410 passed, 0 failed** (405s); targeted guard set (`test_orphan_manifests`, `test_spoke_rbac_covers_manifests`, `test_monitoring_diff`, `test_k8s_render`) → 72 passed. `test_orphan_manifests` unions both routes, so dual registration is not an orphan. The only check is the `! grep -q …` inside `features.json` f1's `verification`, and no workflow in `.github/workflows/` runs features verification. Violation never occurred in reality (file currently absent, header + tasks.md warnings present) → THEORETICAL. | **UNTESTED** — the mutation itself proves no named test covers this path | tests (a pytest asserting the manifest is absent from the base kustomization `resources:`; ~5 lines) |
| Minor | THEORETICAL | admission | The documented danger category (a kube-system container declaring `requests.memory` > 384Mi with no limit would be **rejected** at admission and stuck failing) is a one-time measurement in the proposal, with no ongoing guard. `test_no_unbounded_containers_after_restart` only inspects `Running` pods, so a workload stuck Pending on LimitRange rejection is invisible to every named test. | proposal.md Risks names this as point-in-time; reviewer live scan 2026-10-10 in both clusters: danger list empty (no Running container with a memory request and no limit). A K3s bump is the plausible trigger, exactly as the proposal says. | UNTESTED | tests (scan kube-system workload specs for request-above-default-limit, or extend `TestKubeSystemGovernance`) |
| Minor | SPECULATIVE | tests | `test_no_unbounded_containers_after_restart` reads only `spec.containers`, not `initContainers`; a pod whose initContainer stays unbounded would satisfy the assertion while violating AC3's literal "zero containers with no memory limit". | Code read of `tests/infra/test_k3s.py`; reviewer live scan 2026-10-10: **0 initContainers** exist in kube-system in either cluster, so no consequence today. | UNTESTED | tests |
| Question / assumption | — | sizing | The 384Mi ceiling is derived from Traefik's **at-rest** footprint (149Mi staging / 170Mi prod, no production traffic load at measurement). Under the very spike this spec guards against, an OOMKilled ingress is the failure the proposal itself names. Already declared as a risk and ticketed to OBS-011 / kubelab#1052 (Traefik's explicit `resources` block). | proposal.md Risks; no loaded figure exists anywhere. | n/a | spec (already declared — disposition in verification.md / track in #1052) |

Code-level checklist over the diff: no injection surface (static YAML + JSON test manifests via heredoc-quoted `kubectl create --dry-run`, no shell interpolation of untrusted input), no secrets, no auth changes, the dry-run probes are read-only against the API, constants are independent of the file under test (anti-self-referential rationale documented in-file). The pre-existing `E501` at `tests/infra/test_k3s.py:249` predates the review base (commit `93cffd6d`, #1037) and is outside `make lint`'s `toolkit` scope — not in this change.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All four ACs verified live by the reviewer (3/4 directly; AC4 historical); negative-path gaps: the unguarded kustomization invariant and the unmonitored admission danger category. |
| Verification       | B | Commands are reproducible and were re-run here (suite, lint, type, both clusters, mutation red-proof); AC4 rests on cited historical output only. |
| Scope              | A   | OBS-009 artifacts touched only by its own commits; diff matches the proposal exactly, no creep. |
| Reliability        | B | Imperative bootstrap path, idempotent apply, hand-delete gap and post-merge prod requirement both documented; no error path silently swallowed. |
| Maintainability    | B | Excellent explanatory comments and independent test constants; test functions approach the 40-line guideline and the file carries one out-of-scope lint nit. |
| Handoff-readiness  | A | proposal/tasks/verification/features.json all current, promotion candidates answered with reasons, lessons cited rather than duplicated. |

### Verdict

**PASS WITH GAPS** — no Blockers; the one Major is **THEORETICAL** (reproduced only as a *coverage* gap, never as an incident), the rubric has no C or D. Per the severity × reality rule the gaps are tracked, not blocking.

### Recommended next steps

Contract set (`proposal.md` / `tasks.md` / `features.json`) is **closed** — these are for the implementer to disposition in `verification.md` or to carry into a follow-up ticket; do not edit contract files on the strength of this verdict.

1. **Guard the kustomization invariant (tests)** — add a pytest asserting `governance/kube-system-limitrange.yaml` never appears in any `kustomization.yaml` `resources:` list, plus a red-proof (`make mutate` or equivalent). This is the single highest-value gap; until it exists, the spec's critical property survives only on a comment. Route: follow-up ticket or a `tests/` addition (either is outside the contract set).
2. **Close the admission blind spot (tests, optional)** — extend `TestKubeSystemGovernance` to (a) include `initContainers` and (b) flag any kube-system workload spec whose declared `requests.memory` exceeds `default.memory: 384Mi` without its own limit, converting the proposal's point-in-time measurement into a standing tripwire.
3. **Sizing question** — record in verification.md that 384Mi was never validated under load; OBS-011 (#1052) should re-check it when Traefik gets an explicit `resources` block.

---

**Verdict**: PASS WITH GAPS.
**`dotf spec archive`**: **advisable** in the current state — fresh review written against the recorded contract digests, no draft tags, promotions answered. AC4's evidence is historical (stated above), the sole Major is a THEORETICAL coverage gap tracked as a follow-up.
**To reach a full PASS**: land the named guard test from step 1 (tests only — no contract edit), then a fresh review round can upgrade the verdict.
