---
spec: "EDGE-002-forge-upload-bound"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "bea9f2b79bb0b495a401cbec221c1a0062910de7"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-11-17"
---

## Adversarial review

**Scope**: EDGE-002-forge-upload-bound (fast-track spec, `spec.md`)
**Sources**: `specs/EDGE-002-forge-upload-bound/spec.md`, `review-request.json`,
`git diff fb496d13d331b0bd84ba944b3212a15f17f54430...HEAD`, with the spec's own
commits `68baf1df` (PR 1, #3592), `f441e53e` (review fixes, #3601), `864a7d57`
(PR 2, #3596) and `bea9f2b7` (evidence docs) read in full. Other commits in the
range were read only where they touch the same files (5dfcabf6 shares
`provision-bee.yml`/`common.yaml` with PR 1 but a disjoint region).

### Spec and task alignment

Contract digest verified with `dotf spec digest EDGE-002-forge-upload-bound`:
`spec.md` = `4591762565…5cad`, matches `review-request.json`. No
`[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in the spec folder.

All 7 checklist items are `[x]`. Mapping, with my verification status:

| Checklist item | Repo-side verification this run | Live evidence (UNVERIFIED here) |
|---|---|---|
| 1. Throwaway push over `gitea:3000`, no prod `PUT` | recipe present in `docs/runbooks/cicd.md`; env/network tests below pass | runs 3526/3532, Traefik log read 2026-11-15 |
| 2. `common.yaml` endpoint + `runner.envs` | code present; `test_jobs_are_handed_the_in_network_forge_endpoint` + mutation (below); `envs` map syntax confirmed against official Gitea config docs (docker pull of `gitea/runner:4.1.0` stalled in this sandbox, not retried) | — |
| 3. Beelink provision `changed=2`→`changed=0`, job prints vars | playbook wiring lines present (`provision-bee.yml:518-519`) | `changed=2`/`changed=0`, guard step in runs 3620/3622 |
| 4. Runbook + onboarding name the variable; imagesensortool switched | runbook section + onboarding step present in `cicd.md` diff | imagesensortool#205, runs 3620/3622 green |
| 5. `readTimeout` rendered with a test (red before, green after) | tests pass; M1/M4 mutations prove red-green | — |
| 6. Staging reproduction — marked **Not applicable** with reasoning (value = Traefik default, no before/after) | reasoning checks out against the code (60 s = default, test pins 60 s) | — |
| 7. ADR-076 amendment; VPS role run | amendment text present and consistent with code (`docs/adr/adr-076…`) | `changed=1`→`changed=0`, e2e 78/31/0 |

Spec-vs-code drift: none found. The spec's two PR descriptions match the diffs
exactly (declaration SSOT `forge_endpoint`/`job_network`, `runner.envs`,
`network:` templating, `--entrypoints.websecure.transport.respondingTimeouts.readTimeout`,
ADR amendment points 1–3, lesson-762 + index row). The residual edge dependency
(token GET still crosses the edge) is stated honestly in spec, runbook and lesson.

### Verification performed this session

- `make worktree-init` (poetry install from lock), then:
- Targeted: `pytest tests/test_gitea_actions_runner.py tests/test_edge_backend_timeouts.py tests/test_beelink_renovate_engine.py tests/test_beelink_renovate_timer.py` → **88 passed**.
- Full suite `make test` → **10903 passed, 97 skipped, 0 failed** (329 s).
- `make lint` → All checks passed, 171 files formatted. `make type` → no issues in 170 files.
- **Mutation probes (each reverted; `git status` verified clean after):**
  - M1: comment out the `readTimeout` flag in `traefik-helmconfig.yaml.j2` → `test_the_edge_declares_how_long_it_reads_a_request[acme0/acme1]` **2 failed** (equivalent to the pre-change state, proving "red before").
  - M2: rename `KUBELAB_FORGE_REGISTRY` in the runner template → `test_jobs_are_handed_the_in_network_forge_endpoint` **failed**.
  - M3: `forge_endpoint: gitea:3000` → `gitea:3001` → `test_the_forge_endpoint_names_gitea_s_container_port` **failed**.
  - M4: `k3s_traefik_websecure_read_timeout: 60s` → `90s` → `test_the_read_bound_is_the_ruled_value` **failed**.
  - M5 (the gap): delete both playbook wiring lines in `provision-bee.yml` → full `make test` **10903 passed, 97 skipped** — no test catches it (finding 1).
- No test was deleted or weakened by this spec's commits (diffs are additions only).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Major | THEORETICAL | tests / rollout wiring | No test asserts that `provision-bee.yml` threads `act_runner_forge_endpoint` and `act_runner_job_network` from `common.yaml` into the `beelink_services` role — the hand-off the node actually renders. Tests inject both vars into the template context directly (`_config()`, `_template_vars()`), so they prove the *template* right, not the *provision path*. A deleted line fails only at provision time (Ansible undefined → loud, fail-closed); a wrong-source line (e.g. reading a different existing key) would stay green in CI and wire a wrong endpoint to the node. The repo's own pattern for this exists (`test_beelink_renovate_engine`/`_timer` parse `PLAYBOOK` for their vars). | mutation M5: both playbook lines deleted → full suite green (0 failed); wiring confirmed present at `infra/ansible/playbooks/provision-bee.yml:518-519` | **UNTESTED** — no named test reads these playbook lines. Nearest pattern: `test_the_endpoint_is_the_forge_on_the_compose_network_like_act_runner` (template-level only) | tests (outside contract set — safe to add beside this verdict; e.g. a playbook-parse test in `tests/test_gitea_actions_runner.py`) |
| Minor | THEORETICAL | rollout / staging | The read-bound declaration is evidenced applied on the VPS only; nothing in the range shows staging's `HelmChartConfig` carrying the flag (`deploy-k3s.yml` supports `ENV=staging`). Value equals Traefik's default, so behaviour is identical either way — the gap is visibility-only: staging stays "silent default" until its next deploy. | spec.md checklist/evidence name only the VPS run (`changed=1`→`changed=0`); `infra/ansible/playbooks/deploy-k3s.yml` header shows the staging target | UNTESTED (live cluster state unreachable from this run) | verification-equivalent disposition (ops run or ticket) — not the contract set |
| Minor | SPECULATIVE | docs / supply chain | The runbook recipe pins `docker/setup-buildx-action@v4` by tag; it says "Pin by commit SHA in a real workflow", but nothing enforces that a product copying the recipe does so. | `docs/runbooks/cicd.md` recipe text | UNTESTED (doc snippet) | docs — surface only; already caveated in the text |
| Question | REAL (observed this session) | archive gate (out of scope) | `dotf spec archive EDGE-002-forge-upload-bound` exited 0 and **archived** while `review.md` held `verdict: PENDING`, instead of refusing without a passing review; it rewrote `spec.md` `status: draft`→`archived` and moved the folder. Tree restored (folder moved back, `git checkout -- spec.md`, digest re-checked and matching). A PENDING (or unparsed/absent) verdict appears not to be treated as failing by the pre-flight. | command output in this session, ~18:05 MST; restore verified by `git status` clean and `dotf spec digest` match | n/a | out of scope (gate implementation) — surface to the owner; do not rely on the gate to reject non-final reviews |

**Not findings (checked and cleared):** `runner.envs` map syntax is correct per
official Gitea/act_runner config reference; the runbook's `bash -e`/`&&`-list claim
about the old guard step is accurate shell semantics; the `|| exit 1` guard fix is
correct; recipe uses job-scoped `DOCKER_CONFIG`, no secrets committed; `envs:` and
`network:` renders are SSOT-driven with `StrictUndefined` in tests (no silent-empty
path in CI); lesson-761 references belong to an unrelated lesson (no dangling refs);
`platform.json` regenerated with the declaration (manifest tests pass).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | Both PRs match the spec exactly; four mutation probes turn the named tests red; no defect found in the code. |
| Verification       | B | Repo-side evidence fully reproducible (suite, lint, type, mutations); the live evidence (provision `changed=` counts, Traefik log windows, Gitea runs, VPS e2e) is specific and recorded but not reproducible from this sandbox — UNVERIFIED here. |
| Scope              | A | The spec's commits touch exactly what the spec names (PR 1, PR 2, evidence docs); the rest of the range is other work that interacts only at shared file regions. |
| Reliability        | B | Guard step fails loud on empty vars; runner-restart rollout documented with idempotent provision evidence; residual token-GET crossing the edge accepted and documented; staging declaration pending (Minor above). |
| Maintainability    | A | Lint and mypy clean; tests read values from the SSOT instead of literals; comments explain WHY throughout; no dead code. |
| Handoff-readiness  | A | Spec evidence recorded in-session, lesson-762 + index, ADR-076 amendment, runbook recipe, promotion candidates all answered. |

Aggregation: all B or above → PASS by rubric. Findings axis: one **THEORETICAL**
Major (UNTESTED) → **PASS WITH GAPS** by the severity × reality rule (no Blocker, no REAL Major, no D).

### Verdict

**PASS WITH GAPS** — one THEORETICAL/UNTESTED Major (playbook→role wiring
unguarded by CI), two Minor, one out-of-scope Question. No REAL Major and no
Blocker, so nothing here blocks the archive; every open item is tracked with a
disposition line above.

### Recommended next steps

- **Finding 1 (tests — outside the contract set, safe to apply alongside this verdict):** add a playbook-parse test asserting `provision-bee.yml` sets `act_runner_forge_endpoint`/`act_runner_job_network` from `common.yaml`'s `gitea_runner` block, following the `test_beelink_renovate_*` pattern; red-green it with mutation M5. If deferred, record it as a bitácora ticket with the M5 output as root-cause evidence rather than leaving it conversational.
- **Finding 2 (ops/verification disposition, not the contract set):** disposition in the next provision/ deploy pass — either run `make deploy TARGET=k3s ENV=staging` for the visibility property on staging, or decline with a reason (value equals the default).
- **Finding 3 (docs):** keep as-is or fold a "pin by SHA" hardening into product onboarding; surface-only.
- **Finding 4 (gate, out of scope):** report to the owner that `dotf spec archive` accepted `verdict: PENDING`; the review pre-flight did not behave as documented.
- Do **not** edit `spec.md`/`proposal.md`/`tasks.md`/`features.json` alongside this verdict — the contract set is closed by PASS WITH GAPS; a contract edit would stale this review and require a re-review.

**Verdict: PASS WITH GAPS. `dotf spec archive EDGE-002-forge-upload-bound` is
advisable in the current state** (with this `review.md` in place and the findings
above dispositioned per the two "next steps" bullets), **noting the gate
observation**: this run watched the archive command succeed on a PENDING verdict,
so the human should treat the gate as accepting, not enforcing, review freshness.
