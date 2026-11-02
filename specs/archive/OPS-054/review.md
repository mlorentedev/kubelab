---
spec: "OPS-054"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "04d12f2f2949a616b6c7e7a3ecdfd87182ad4beb"
reviewer: "nan/deepseek-v4-flash"
date: "2026-11-02"
---

## Adversarial review

**Scope**: OPS-054 — `make load-test ENV=staging`, a repeatable k6 capacity measurement
of staging (bitácora mlorentedev/kubelab#2956).
**Sources**: `specs/OPS-054/{proposal,tasks,verification}.md`, `specs/OPS-054/features.json`,
`specs/OPS-054/review-request.json`; `git diff e2721a44921135ca2a549cefd2d461c7233494ba...HEAD`
(base resolved by the launcher, not substituted); `git log e2721a4..HEAD`
(`2969aa5d`, `17673ecf`, merge `04d12f2f`). `dotf spec digest OPS-054` matches the
`contract_digests` in `review-request.json` for all three contract files, so this verdict
is about the contract as it stands.

**Commands actually run in this session** (evidence, not assertions):
`poetry run pytest tests/test_load_test.py -q` → **47 passed**; `poetry run ruff check` →
clean; `poetry run ruff format --check` → 3 files already formatted; `poetry run mypy toolkit`
→ *Success: no issues found in 152 source files*; the seven `features.json` verification
commands → all exit 0 (f2 run as `poetry run pytest`, see F4); `toolkit infra load-test run
--env prod|dev` → refused, exit 1; report figures re-computed from
`docs/load-test/2026-11-02-7ccf57f4.json`.

### Spec and task alignment

- **AC1** (in-repo, one documented command, pinned) — `Makefile` `load-test` target, runbook
  `docs/runbooks/load-test.md`, `load_test.image: grafana/k6:2.3.0` recorded with its digest at
  run time (`facts.k6_image` = `grafana/k6@sha256:2dd4756e…bdb0fba0b8`). Met.
- **AC2** (staging only, refuses prod by construction) — `refuse_unless_staging`, host regex +
  prod-host intersection in `build_targets`, prod VPS addresses refused in `resolve_nodes`,
  kubeconfig pinned to the single staging node in `assert_cluster`; `constant-rate.js` repeats
  the host check and `maxRedirects: 0`. Ran the CLI: `--env prod` and `--env dev` both exit 1.
  Met, with negative tests.
- **AC3** (percentiles, error rate, throughput, concurrency, node use) — every column present in
  `render()` and in the committed JSON; verified by recomputation: 800/s worst p50 1.09 ms, p95
  1.87 ms, p99 146 ms, node CPU 43.4 %; 1000/s worst p95 2.35 ms, p99 97.9 ms, node CPU 48.5 %,
  383 peak VUs; generator max 33.9 %; throttling max 141 ms; zero 429 on the bypass. Every number
  in `docs/load-test/report-2026-11-02.md` that I checked matches the raw file. Met.
- **AC4** (limiter handled by declared, reversible config; method says what changed) —
  `infra/load-test/limiter-bypass-route.yaml` is header-scoped, outside `infra/k8s`, applied and
  deleted by the run, and stated in the report. The claim that a leftover fails
  `tests/infra/test_rate_limit.py` is **true** (that test asserts every live IngressRoute carries
  `rate-limit`), but it only fires when someone runs the `infra`-marked suite — see F2.
- **AC5** (date, commit, hardware, method) — `result.date`, `result.commit`, `result.facts`
  (k6 digest, Traefik image, k3s/kernel, CPU model, node capacity, per-workload image and
  resources) + report + runbook. Met, with the provenance caveat in F9.
- **AC6** (how staging differs from prod) — report section present and specific (ARM64 CAX21 vs
  N95, LAN vs internet, limiter on/off, versions); the "may not be used to imply" list is
  stronger than the criterion asks. Met.
- **AC7** (defects fixed or ticketed with root cause) — #2975 (LimitRange-inherited 384 MiB),
  #2977 (in-flight timeouts on web rollout) and #3000 (results lost when a step raises) all exist,
  are OPEN, and carry root cause. Met.
- **tasks.md** — the four implementation boxes are ticked and each is backed by files in the diff.
  The Closing section is entirely unticked although the work is done; `verification.md` keeps its
  template "Test status" placeholder and its three "Promotion candidates" lines unanswered, which
  the archive gate refuses (F5).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Major | THEORETICAL | Resilience | A step that raises aborts `run()` and the CLI writes the result files only after `run()` returns, so a two-hour run that hits a pod-less moment (edge mid-crash, `wait_for_stable_edge` → `restarts`/`edge_ready`, `run_step` → `pod`, a failed `disarm`) discards **every measured ramp**. This is exactly the scenario the tool exists to create — it drives Traefik to OOMKill. | #3000's root cause names the same three paths; `toolkit/cli/infra.py` writes `base.with_suffix(...)` only after `return`; `Lab.pod` raises `LoadTestRefused` on an empty Running set. #3000 says it "did not happen in the 2026-11-02 runs", and the committed run completed, so no reproduction | UNTESTED | code + tests (ticketed #3000 — disposition: tracked) |
| Major | THEORETICAL | Security | If a run dies before its `finally`, the header-scoped route stays and `X-Load-Test: ops-054` — a value committed in git — bypasses the limiter on two staging hosts, with no automatic alarm: `pyproject.toml` `addopts` is `-m "not e2e and not infra"`, so the only detector (`tests/infra/test_rate_limit.py`) runs when a human types `make test-infra`. Impact bounded: ADR-052 §25 says only the mesh (and LAN) reaches staging; endpoints are `/health` and a static page. | route manifest + `pyproject.toml:116` + runbook "If a run dies"; no CI job proven to run `infra` (UNVERIFIED) | UNTESTED | code + tests (pre-flight refusal on a leftover route, or a scheduled check) — disposition: tracked |
| Minor | REAL | Data contract | `knee()` emits `vus_at_last_healthy` (a value) together with `last_healthy_rps: null`, and collapses two different meanings into `lower_bound_only: true`: "a lower bound" (generator / never degraded) and "measured nothing" (limiter / rollout). A consumer cannot tell them apart without re-reading `reasons`. Inert in the committed data (all six ramps have a knee). | `lt.knee([{rate:100,reasons:[],vus_peak:3},{rate:200,reasons:['limiter'],vus_peak:9}])` → `last_healthy_rps: None, first_degraded_rps: 200, lower_bound_only: True, vus_at_last_healthy: 3` | UNTESTED (the invalidity cases assert only `last_healthy_rps`/`lower_bound_only`) | code + tests |
| Minor | REAL | Contract / harness | `OPS-054-f2`'s `verification` is `.venv/bin/python -m pytest …`; in this worktree there is no `.venv`, so the literal command exits **127** and the feature can never reach `passing`. Every other active spec's `features.json` uses `poetry run pytest`. A bootstrapped worktree (`make worktree-init`) does create `.venv`, so this is environment-dependent; the behaviour itself is proven (`poetry run pytest` → 47 passed). | `bash -c '.venv/bin/python -m pytest tests/test_load_test.py -q'` → exit 127; `grep` of `specs/*/features.json` shows `poetry run pytest` as the convention | UNTESTED (harness) | contract (features.json) — **note: editing it stales this review; re-run `dotf spec review OPS-054` if you change it.** Bootstrap the worktree or decline with a reason to keep the current signature |
| Minor | REAL | Spec artifacts | `verification.md` still carries its template placeholders: "Test status" is `<command> -> <output>` and all three "Promotion candidates" lines are unanswered. `dotf spec archive` has a third pre-flight that refuses every unanswered promotion line and **no flag skips it**, so archive will fail even with this passing review. Outside the contract set, so filling it does **not** stale this verdict; ticking `tasks.md` boxes does not either (digests normalise checkbox ticks). | `dotf spec archive --help` (third pre-flight); `specs/OPS-054/verification.md` Promotion candidates section | n/a | spec artifacts (verification.md; tasks.md Closing ticks) |
| Minor | REAL | Scope | `.agent/unattended.yml` (+69 lines) — the unattended run's arming file — rides in this PR (its own commit, `2969aa5d`). It is not part of OPS-054, and it records operator authority (staging load that may restart the ingress, prod provisioning for #2975) that belongs to the run, not to a load-test feature. | `git diff … -- .agent/unattended.yml`; `git log --oneline e2721a4..HEAD` | n/a | code (land it with the run, not the feature) — disposition: tracked/declined |
| Minor | REAL | Quality | The two new Makefile targets were inserted **between** the `edge-measure` explanatory comment block and the `edge-measure` target, so that comment now introduces the wrong recipe. | `git diff … -- Makefile` (comment block, then `+.PHONY: load-test`, then `.PHONY: edge-measure`) | n/a | code |
| Minor | THEORETICAL | Injection | `k6_command` builds the remote command by string interpolation of config-derived values (`-e {key}={value}`) and `Lab.ssh` hands it to a remote shell unquoted. A value containing shell metacharacters (or a future config-driven value) becomes remote command injection, where the rest of this tool passes literals. | `toolkit/features/load_test.py` `k6_command` + `Lab.ssh` | UNTESTED | code (`shlex.quote` every interpolated value) |
| Minor | REAL | Provenance | The results record `commit: 7ccf57f4`, which is **not** an ancestor of HEAD (squash/rebase), and were produced by a tool slightly older than the merged one (report discloses both under "Tool changes after these runs"). The method is reproducible from the merged tool; the exact artifact is not. | `git merge-base --is-ancestor 7ccf57f4 HEAD` → not ancestor; `git cat-file -t 7ccf57f4` → commit exists but is unreachable from any branch | n/a | docs (already disclosed) — disposition: accept, or record the tree/digest next run |
| Minor | REAL | Quality | `run()` is 56 lines and `knee()` measures ≈11 cyclomatic complexity, both over this repo's stated limits (<40 lines, CC <10). Also `_load_test_results_dir`'s docstring says the directory "exists before a two-hour run needs it", while the CLI creates it only *after* `run()` returns. | AST measurement of `toolkit/features/load_test.py`; `toolkit/cli/infra.py:317-321` vs line 371 | UNTESTED | code |

**Strength that directly mitigates a documented risk** (not praise for balance): the design fails
**safe**, not quiet. If the bypass route does not take effect, the step sees 429s → `limiter` →
the ramp's figure is discarded rather than reported as capacity; a rollout or edge restart is
recorded rather than averaged in; and `cleanup` removes the k6 image even when deleting the route
fails (`TestCleanup::test_the_image_goes_even_when_the_route_could_not`). The absence of any 429 at
50/s and above in the raw data is what proves the bypass was in force — an inference, but a sound
one.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | B | All seven ACs met and negative paths tested (prod/dev refusal, non-staging host, prod address, shared generator, knee/limiter/rollout); one inert inconsistency in `knee()` (F3). |
| Verification       | B | Strong and reproducible: 47 tests, ruff, mypy, CLI refusals and a report re-derived from the raw JSON all ran green here; `verification.md`'s Test-status block is still a placeholder and the feature evidence is harness-pending. |
| Scope              | B | Diff matches the proposal (tool, tests, runbook, results, report, lesson); one unrelated 69-line arming file (F6) and a build-regenerated `platform.json`. |
| Reliability        | B | Cleanup in `finally` with a second fallback, edge-recovery wait, fail-safe classification; the results-losing raise path is real but ticketed (#3000, F1). |
| Maintainability    | B | Typed throughout, ruff+mypy clean, comments explain *why*; `run()` over the 40-line rule and `knee()` near the CC limit (F10). |
| Handoff-readiness  | C | Runbook, report, lesson and tickets are in place, but `verification.md` placeholders are unfilled and the archive gate refuses them (F5); closing checklist unticked. |

### Verdict

**PASS WITH GAPS** — no Blocker, no REAL Major, no rubric D. Two THEORETICAL Majors (results lost on
a raising step; leftover bypass undetected automatically) are both tracked — the first by #3000 with
the correct root cause, the second by a recommendation below. The gap that costs something today is
Handoff-readiness C: the spec folder is not archive-ready yet, and the fix is outside the contract set.

### Recommended next steps

Contract set (`proposal.md`, `tasks.md`, `features.json`) is **closed** under this verdict — changing
it stales the review and needs `dotf spec review OPS-054` again. Everything below is outside it:

1. **`verification.md`** (disposition: apply) — replace the "Test status" placeholder with the
   commands and results actually observed (e.g. `poetry run pytest tests/test_load_test.py -q` → 47
   passed; `poetry run ruff check` / `ruff format --check` / `mypy toolkit`; `toolkit infra load-test
   run --env prod` → exit 1), fill "Decisions made during implementation" (the edge-restart verdict
   and the 120 s wait, the k6 result-loss decision deferred to #3000), and answer all three
   "Promotion candidates" lines — my reading is `yes: docs/lessons/kubernetes/lesson-696-a-load-tests-limit-can-be-a-limit-nobody-declared.md`,
   `no: the decisions are recorded in the proposal and the report, no ADR is warranted`, and
   `no: load testing is a per-repo method, not a cross-project pattern`. `dotf spec archive` refuses
   until these are answered.
2. **`tasks.md` Closing** (disposition: apply) — tick the six boxes now that they are true; the digest
   normaliser ignores checkbox ticks, so this does not stale the review.
3. **F1 / #3000** (disposition: tracked) — fix is already specified there; add the named regression
   test it asks for (`run()` keeps finished ramps when a later step raises) and cite it in
   `verification.md` when closed.
4. **F2** (disposition: tracked, one line of work) — add a pre-flight to `load-test-run` that refuses
   while an `IngressRoute/load-test` exists (`kubectl get ingressroute load-test` → if present, exit
   non-zero naming `make load-test-clear`), or wire `tests/infra/test_rate_limit.py` into whatever
   periodic job already runs the `infra` suite. The header value is in git, so the guard is worth
   having regardless of ADR-052's mesh-only boundary.
5. **F4** (disposition: track or decline) — either bootstrap the worktree (`make worktree-init`
   creates `.venv`) and leave `features.json` alone, or change f2 to `poetry run pytest` in a
   follow-up round; do **not** edit `features.json` under this review.
6. **F3, F7, F8, F10** (disposition: track) — code-quality follow-ups: give `knee()` a distinct
   `measured: false` flag instead of overloading `lower_bound_only`, `shlex.quote` the k6 env
   values, restore the `edge-measure` comment to its target, split `run()`.
7. **F6** (disposition: decline with reason, or split) — `.agent/unattended.yml` is the run's
   arming file; keep it out of the feature PR or say so in the PR body.
8. **F9** (disposition: accept) — the report already discloses the orphaned commit; on the next
   run the tool could record `git rev-parse HEAD` plus the tree hash so a squashed history still
   resolves.

**Archive advisability**: not yet — `dotf spec archive OPS-054` will refuse on the unanswered
promotion lines (item 1). Once `verification.md` is answered, the review is still fresh
(verification.md is outside the staleness set) and archive is advisable. If a Blocker or a REAL
Major is later found, the flip back to PASS needs only the code/test fix in F1/#3000 — nothing in
the contract set.
