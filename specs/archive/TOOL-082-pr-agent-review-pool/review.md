---
spec: "TOOL-082-pr-agent-review-pool"
verdict: "PASS"
reviewed_sha: "a33748c72ea6427d818810b574df2e3efe750ce5"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-10-15"
---

## Adversarial review

**Scope**: TOOL-082-pr-agent-review-pool, whole change `git diff 0a1f82f1cd5a151d414545cee96b9c94162def2e...HEAD` (base as resolved by the launcher; HEAD `a33748c7`)

**Sources**: `specs/TOOL-082-pr-agent-review-pool/{proposal,tasks,verification}.md`, `features.json`, `.github/workflows/pr-agent.yml`, `scripts/pr-agent-{model-preflight,route,publish-guard}.sh`, `harness/reviewer-pool.json`, `.pr_agent.toml`, `tests/test_pr_agent_*.py`, `tests/test_reviewer_pool.py`, `docs/adr/adr-070-*.md`, `docs/runbooks/pr-agent-reviewer.md`, `docs/lessons/ci-automation/lesson-575-*`, commits `0a1f82f1..a33748c7`

### Verification performed (fresh, this session)

| Claim | Command | Result |
|---|---|---|
| Five PR-Agent suites + pool | `poetry run pytest tests/test_pr_agent_{preflight,route,publish_guard,workflow}.py tests/test_reviewer_pool.py -q` | **186 passed**, exit 0 — matches verification.md's count |
| Full suite | `make test` at a33748c7 | **5180 passed, 18 skipped, 164 deselected, 2 xfailed**, exit 0 (465.95 s) |
| Lint | `make lint` (ruff check + format) | exit 0, "All checks passed!" |
| Scripts lint | `shellcheck -S style` on the three scripts | clean, rc 0 |
| Workflow lint | `actionlint .github/workflows/pr-agent.yml` | exactly 5 SC2016 infos, same 5 present at base 0a1f82f1 (verified against `/tmp/pr-agent-base.yml`) |
| Mutation: risk threshold | `scripts/pr-agent-route.sh` `-ge` → `-gt` on the risk line | **2 failed** (`test_the_shipped_pool_routes_to_sonnet_at_1500_changed_lines_and_not_below`, `test_a_pr_at_the_line_threshold_reviews_first_on_the_risk_member_nan_second`) — reverted |
| Mutation: preflight 2xx | `2??)` → `2xx)` | **10 failed, 3 passed** — reverted |
| Mutation: second-attempt gate | `published == 'false'` → `!= 'true'` in the NaN attempt's `if` | **1 failed** (`test_a_second_attempt_runs_only_on_a_measured_absence`) — reverted |
| AC5 live | `gh run view 38686296555 --log` | `PR-Agent reviews first on anthropic/claude-haiku-5-5 (draw, override: draw); second attempt: nan` + `review published (markers: ["## PR Reviewer Guide"]) on anthropic/claude-haiku-5-5` — matches verification.md verbatim |
| AC6 live | `gh run view 38685369694 --log` | `reviews first on anthropic/claude-sonnet-5-5 (risk, override: draw)` + `review published ... on anthropic/claude-sonnet-5-5` — matches verification.md verbatim |
| AC1 CLI enforcement | `dotf spec review ... --dry-run --reviewer anthropic-review/claude-haiku-5-5` | refused: "it is a fallback, which signs first only when the first signers failed: pass --fallback-reason"; with `--fallback-reason quota` and with `nan/glm5.3-flash` the launch command builds — matches verification.md |
| Tree clean | `git status --short` | only the launcher's `review-request.json` (untracked); all mutations reverted |

### Spec and task alignment

- **AC1** — `tests/test_reviewer_pool.py` (8 tests: vendor, exactly one credential path, Anthropic never signs first, another vendor can sign first, drawable members, risk member, risk predicate) plus `test_every_model_pr_agent_reviews_with_is_admitted_in_the_reviewer_pool` cover the pool schema; all green. `docs/adr/adr-070` records amendment B. CLI enforcement reproduced above. **Met.**
- **AC2** — `tests/test_pr_agent_preflight.py` (13 tests, incl. 3 real-curl/HTTP-server tests); chain equality asserted at `test_pr_agent_workflow.py:1240` (`DECLARED_FALLBACK_MODELS == toml fallback_models`) and `test_the_workflow_reviews_with_the_toml_model` (`DECLARED_MODEL == toml model`). Warning names model + status class (test `the_warning_names_the_fix_by_status_class_not_one_remedy_for_all`). Mutation `2??`→`2xx` turns 10 red. **Met.**
- **AC3** — `tests/test_pr_agent_route.py` (43 tests): cumulative weight at every point, dead member's weight shared, 1500/not-1499, exact label, Sonnet never drawn (`test_the_shipped_pool_draws_each_member_exactly_its_declared_weight`, `test_a_risk_member_is_probed_only_for_a_risky_pr`), allowlist refusal before any probe, unknown override exit, key on curl stdin only, price ceiling (`test_the_worst_anthropic_review_stays_under_its_ceiling` in workflow tests). Mutation `-ge`→`-gt` turns 2 red. **Met.**
- **AC4** — `tests/test_pr_agent_workflow.py` (65 tests) + `tests/test_pr_agent_publish_guard.py` (26 tests): attempt order the guard reads, one pinned action, the two Anthropic copies identical (`test_the_two_anthropic_attempts_are_one_step_written_twice`), equal review settings, per-attempt key separation, second attempt gated on a measured absence (mutation-verified above), job timeout ≥ worst two-attempt path, sparse checkout without credentials, marker read from the shared registry and absent as a literal from workflow and script. Attestation tests (gate name, pr-number artifact, concurrency groups) green in the full run. **Met.**
- **AC5 / AC6** — live evidence reproduced from GitHub above (both run ids, both logs match verification.md). The `deep-review` label route is unit-tested only; AC6's "either … or" is satisfied by the live size route. **Met.**
- **Contracts preserved** — workflow name `pr-agent` (`test_the_gate_re_evaluates_on_the_reviewer_workflow_by_its_real_name`), `pr-number` artifact first (`test_the_upload_precedes_the_reviewer_so_a_cancelled_run_still_carries_it`), reviewable/stale-label/declare-unreviewed steps unchanged in substance, concurrency groups with `queue: max` intact, Dependabot/release/deploy skips intact. **Met.**
- No test was deleted: zero `def test_` lines removed from `tests/test_pr_agent_workflow.py` (52 → 65), and the only deleted assertions (registry-in-run, marker-not-literal, old single-step `if`) have named successors cited above. The other deleted test lines in the scoped diff belong to master PRs #2300/#2303, not this spec.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec artifacts | `tasks.md` Closing leaves `[ ] make test passes; make lint passes` unticked although both pass fresh at the reviewed sha (evidence table above: 5180 passed exit 0; lint exit 0) | my runs at a33748c7 | n/a — contract artifact | spec (tick only; checkbox ticks are excluded from the staleness digest, so ticking does not invalidate this verdict) |
| Minor | REAL | spec artifacts | `tasks.md` ticks `[x] Adversarial review (dotf spec review) before archive` while `specs/TOOL-082-pr-agent-review-pool/review.md` did not exist at launch (`ls` at session start showed no review.md) | directory listing before this write | n/a — contract artifact | spec (now satisfied by this artifact; tick was premature) |
| Minor | REAL | scope | The launcher-scoped diff `0a1f82f1...HEAD` carries 8 files (toolkit/, traefik test, ADR-064 amendment, Makefile comment) belonging to 4 unrelated PRs (#2297, #2300, #2303, #2306) that landed on `origin/master` and were merged into the branch by `9d8e35a7`; the spec's own delta `origin/master...HEAD` is 10 files and matches the proposal exactly. So `tasks.md` "[x] No unrelated changes in the diff" is true of the spec's commits, not of the literal scoped diff | `git log --oneline 0a1f82f1..origin/master`; `git diff --name-only origin/master...HEAD` | n/a — not the spec's code | none required; a one-line note in `verification.md` (outside the contract set) if the owner wants the tick defensible as scoped |
| Minor | SPECULATIVE | security/robustness | An Anthropic/NaN key containing a `"` would break curl's `-K -` config line inside `probe()`; curl then fails, the code reads `000`, and the member is dropped with a misleading "gave no answer within 30s" note. Fail-closed (review falls to the other provider with a note), and provider-issued keys do not contain quotes — hence SPECULATIVE, surface only | code read of `probe()` in both scripts; no reproduction | UNTESTED | code (optional hardening: strip/reject quote chars before building the config line; follow-up ticket, not gating) |
| Minor | REAL | perf/cost | On a risky PR under `draw`, the route probes Haiku (64 tokens) before it probes Sonnet, so two paid probes run where one would do | code read: the `drawn_anthropic` probe block precedes the risk block in `pr-agent-route.sh` | UNTESTED (behavior; cost trivial) | code (optional; not gating) |
| Question / assumption | THEORETICAL | trust boundary | The PR head's scripts execute next to both credentials (draw holds `PR_AGENT_ANTHROPIC_API_KEY`, preflight holds `NAN_API_KEY`). This is the same trust class as the head-supplied workflow file a `pull_request` run already takes; forks and Dependabot are excluded by the job `if:`; it is documented and accepted in `docs/runbooks/pr-agent-reviewer.md` §"What the job trusts" and dispositioned in verification.md round 1 | runbook text + workflow `if:` conditions | `test_the_scripts_are_checked_out_sparsely_and_without_credentials` (credentials not persisted; exposure itself is documented, not tested) | none — owner-accepted; revisit if the job ever moves to `pull_request_target` |

No Blocker and no Major found. Every acceptance criterion has named tests and each mutation claim in `verification.md` reproduced exactly.

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All six ACs verified — three mutations bit red as claimed, both live runs reproduced from GitHub, no observed defects in code or contract |
| Verification       | A | evidence is reproducible commands with outputs; I re-ran the full suite, lint, shellcheck/actionlint, 3 mutations, 3 CLI dry-runs and 2 run logs — every claim matched |
| Scope              | B | The spec's own delta vs origin/master is exactly the proposal's 10 files, but the launcher-scoped diff also carries 4 unrelated already-merged master PRs (merge `9d8e35a7`), so the literal reviewed diff is wider than the proposal |
| Reliability        | A | Outages fail closed throughout: unknown probe → `unknown` never runs the second attempt, API failures never read as "no review", draw failure stops spend, guard goes red naming the last attempt that ran |
| Maintainability    | B | Tests are precise and well-named; the three shell scripts are heavily documented but `route.sh` and `measure()` run long with deep case nesting, near the repo's function-size line |
| Handoff-readiness  | A | ADR-070, runbook, lesson-575, features.json and a decisions log are all in the diff; promotions answered |

Aggregation: all dimensions ≥ B, no Blocker, no REAL Major → **PASS**.

### Verdict
PASS

### Recommended next steps
- **Contract set is closed** — this verdict permits archive; do not edit `proposal.md`, `tasks.md` content, or `features.json`. Ticking the two checkbox lines in `tasks.md` is safe (ticks are excluded from the staleness digest) and lets `dotf spec archive`'s task check pass if it applies one.
- Optional, in `verification.md` (outside the contract set): record the scope note about the four master PRs inside the launcher-scoped diff, and record this review's three reproduced mutations.
- Follow-up tickets (code, non-gating): quote-sanitisation in `probe()`'s curl config line; skipping the Haiku probe when the risk route already answered.
- **`dotf spec archive TOOL-082-pr-agent-review-pool` is advisable** once the two checkbox ticks above are made: this review is fresh (contract digests recorded by the launcher at 2026-10-15T06:16:37Z over an unchanged working tree at `a33748c7`), no `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags remain in any spec file, and the promotions section is answered.

---

**Definition of Done (reviewer's closing pass):**
*Debt* — the five findings above are listed with dispositions; none left verbal. *Knowledge* — nothing learned this session that the diff does not already record (the launcher's digest algorithm is not raw sha256; working-tree identity plus `reviewed_sha` covers staleness). *Board* — not applicable to this run; the review writes no commits and touches no ticket state, per the launcher's instructions. *Review* — no PR comments are acted on here, per the launcher's instructions. *Evidence* — every claim above is backed by command output produced in this session (table at top).
