---
spec: "CI-001-pytest-xdist"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "7017895da4d910e046feeabdb3e841b7cd74e2b4"
reviewer: "nan/mimo-v2.6-flash"
date: "2026-11-09"
---

## Adversarial review (round 2, pooled)

**Scope**: CI-001-pytest-xdist (mlorentedev/kubelab#3078), covering the whole change from the launcher-resolved base `6bf8a5bb` — that is the spec's two merged PRs (#3098 `d7b057af`, #3124 `dff0b0a3`) plus this branch's four commits (`e86ed7fc`, `79702a03`, `73079aa8`, `7017895d`), judged as one change including the late fixes that respond to round 1.
**Sources**: `specs/CI-001-pytest-xdist/{proposal,tasks,verification,features}.md`, `review-round1.md`, `review-request.json`; `git diff 6bf8a5bbbaec0c40f9b30b47ac510799c8251b4c...HEAD`; PR #3225 checks and CI run logs (read-only).

### Spec and task alignment

- **Contract set fresh**: `dotf spec digest CI-001-pytest-xdist` matches `review-request.json`'s `contract_digests` exactly (features.json / proposal.md / tasks.md). No `[AGENT-DRAFT]`/`[AGENT-SUGGESTION]` tags in any spec file.
- **All six features.json verification commands re-run this session, all exit 0**: f1 (4 passed), f2 (1 passed), f3 (grep exit 0), f4 (8 passed), f5 (3 passed), f6 (22 passed).
- **Gates fresh**: `make lint` clean ("All checks passed!", 161 files), `make type` clean (160 files, no issues), ruff `C901` at max-complexity 10 clean on the new files.
- **Full suite fresh at the reviewed sha**: `make test` → **9443 passed, 95 skipped, 0 failed, 5m12s**. (verification.md's AC5 local figures — 8982 passed / 32 macOS environment failures — are commit-stamped historical evidence; master's #3133 later fixed those macOS failures, so the recorded set no longer reproduces at HEAD. That is an accuracy note on verification.md, not a defect: it is dated evidence outside the contract set.)
- **CI fresh at the reviewed sha**: PR #3225's `Tests` job **success** on `7017895d`; shards 6m29s/5m06s/6m46s; combine step reads "Combined 3 files" (lesson-713's own trap is avoided) with `TOTAL 21329 4704 6390 571 76%` against the local single-run `TOTAL 21329 4706 6390 571` — statement, branch and partial counts identical; the 2-statement missed delta is macOS vs Linux, not shard loss. The recorded AC6 CI-vs-CI equality (20362/4619/6070/548 on runs 41990181968 vs 41982806229) stands as the commit-stamped proof.
- **AC2 re-measured end-to-end**: `make tests-p50 SINCE=2026-11-05T08:13:42Z` → exit 0; first 20 = 15.4 / last 20 = **9.0** / all 146 = 13.2 min wall, with queue, agg, skew, per-window drop columns printed; "last 20 p50 is 9.0 min, within 10.0 min". The operator's acceptance of the last-20 window (2026-11-09, recorded in verification.md with all three windows) is the AC2 definition; the first/all windows remain over 10 because of the 2026-11-06 (UTC) saturation, which is ticketed as CI-002 (#3223, body reads "On 2026-11-06 (UTC)" — round-1 disposition #8 confirmed) and written up in lesson-728 (now quoting 14.1 over 139, matching the command's own output — disposition #6 confirmed).
- **Round-1 dispositions verified against the code, not the prose**: queue column outside wall (#1, `test_queue_is_creation_to_first_shard_start_and_stays_outside_wall`); reruns dropped before their jobs are ever fetched (#2, `test_a_rerun_is_dropped_because_its_jobs_mix_attempts` asserts the fetch never happens); dropped-run counting per window with the cancelled-during-queue bias stated in the module docstring (#3, `test_the_report_carries_each_windows_drops`, `test_dropped_runs_are_counted_inside_the_window_they_fell_in`); CLI exits 0/1/2 and under-sampling exit 2 (#4, `test_the_command_exit_status[under-sampled]`, `test_the_command_exits_2_when_the_runs_cannot_be_read`); last-window-as-signal documented in `--help` (#5, doc only — see findings); agg column plus the exact identity `wall = shard phase + wait + aggregate` with an assertion that the columns do NOT partition (#7, `test_wall_is_the_shard_phase_plus_wait_plus_aggregate_and_skew_overlaps_it`); `--since` normalised and naive values refused (#9, `test_since_is_normalised_to_a_utc_instant`, `test_a_since_without_a_timezone_is_refused`).
- **Mutation probes run this session, tree restored clean afterwards**: (a) neutralised the ci.yml gate's `exit 1` → `test_the_gate_step_exits_non_zero_on_every_result_but_success` and `test_the_required_check_fails_when_any_shard_did_not_pass` went red (4 failed); (b) removed `-n auto` from the Makefile recipe → `test_make_test_spreads_the_suite_over_every_cpu` went red; (c) forced `assign` to put every file on shard 1 → `test_shards_differ_by_no_more_than_the_heaviest_file` and `test_the_plugin_deselects_other_shards_and_runs_unknown_files` went red (2 failed). Note for the record: the headline `test_every_file_runs_on_exactly_one_shard` alone does NOT catch (c) — an all-on-one plan is still a valid partition — but the file's balance and end-to-end tests do, so the guard set as a whole holds.
- **Scope**: the four branch-authored commits touch only spec-named files (ci.yml, Makefile, tests, toolkit ci_timing/tools, spec folder, lessons). The range contains ~80 further commits — master work that reached the branch through integration (the range has zero merge commits; the launcher's `--first-parent --no-merges` log separates them) — not work authored by this spec. The interaction points were checked and cohere: master's `make setup-ansible` step (#3203) runs inside the new aggregate job and installs its poetry group `ansible`; `system_path` (#3133) and `pytest_plugins = ["tests.sharding"]` coexist in `tests/conftest.py`; `shard-durations*.json` is gitignored (`.gitignore:54`).
- **PR checks triaged**: everything green except the **Spec archive gate**, which fails **by design at this stage** — its own log says the PR closes #3078 without archiving, and prescribes `dotf spec archive` *which requires this passing pooled review first*. It is sequencing, not a defect; it flips once the archive runs. `declare`/`CodeRabbit`/`API`/`Errors` are path-conditional skips; `review-attestation` reports "a review happened".

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Minor | THEORETICAL | tests-p50 exit contract | The exit status gates on `windows[1]` (last window), but no test distinguishes that from gating on the first window: every fixture in `test_the_command_exit_status` is uniform (`[8.0]*20`, `[12.0]*20`, `[8.0]*19`), so a regression to `windows[0]` stays green while `--help` keeps claiming "the last window". Round-1 disposition #5 chose a docs fix; the test half remains open. | `tests/test_ci_timing.py::test_the_command_exit_status` walls; `toolkit/cli/tools.py` (`last = windows[1]`) | UNTESTED (extend `test_the_command_exit_status` with non-uniform walls) | tests |
| Minor | SPECULATIVE | error path | `tests-p50` documents exit 2 "when the runs cannot be read", but the `try` catches only `RuntimeError`/`ValueError`/`KeyError`; a missing `gh` binary (`FileNotFoundError`) or a `gh api` timeout (`subprocess.TimeoutExpired`, `GhApi._run` sets `timeout=60`) escapes as a traceback with exit 1 instead of 2. No observed occurrence — `gh` was present and all runs completed here. | `toolkit/cli/tools.py` try block against `toolkit/features/deploy_shape.py::GhApi._run` | UNTESTED (only the `RuntimeError` path is covered: `test_the_command_exits_2_when_the_runs_cannot_be_read`) | tests + code (broaden the catch, or narrow the docstring) |
| Minor | REAL (measured) | code quality | `tests_p50` spans 45 lines from `def` to its last statement, over the repo's `< 40 lines` function rule (body without the `Annotated` signature and docstring is ~31, so the reading matters). Cyclomatic complexity is fine (C901 ≤ 10 clean). | `awk` line count on `toolkit/cli/tools.py` = 45 | n/a (style rule) | code (extract the table rendering) |
| Minor | THEORETICAL | verification | AC1's serial-vs-xdist count/coverage parity is proved only at its commit-stamped commits (`d2e92f4c` locally; CI run 41954054691 vs base `98eef0d0`), not re-run at the reviewed sha. The recipe and `addopts` it proved are unchanged in the diff since, the fresh parallel run is 9443/0 and CI is green — the residual risk is an order-dependent test added by master's later commits, which a parallel-only run would not expose. | verification.md AC1 line against the current tree | UNTESTED (a serial `pytest` run at HEAD would be the evidence) | verification.md (rerun, or explicitly accept the recorded evidence) |

All four are outside the contract set (`proposal.md` / `tasks.md` / `features.json` untouched by them).

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | Every acceptance criterion verified against code or fresh runs; only minor negative-path gaps (exit-path variants, window-choice test) remain. |
| Verification | A | Six feature commands, lint, type, full suite, `tests-p50` and the CI combine all re-run this session with outputs, plus three red mutation probes and the recorded CI run IDs. |
| Scope | B | Branch-authored commits touch only spec files; the range also carries pre-merged master work whose interaction points were checked and cohere — noise is integration, not creep, but it is in the diff. |
| Reliability | B | Gate step executed for all four `needs` results, API failures mapped to exit 2, under-sampling refused; the missing-`gh`/timeout path still exits 1 with a traceback. |
| Maintainability | B | C901 ≤ 10, lint and mypy clean, docstrings carry the why; `tests_p50` exceeds the 40-line function rule. |
| Handoff-readiness | A | Lessons 710/712/713/728, promotion lines answered, round-1 dispositions recorded, follow-up CI-002 (#3223) ticketed. |

### Verdict

**PASS WITH GAPS** — no blockers, no majors; four minors, each with a disposition line above; rubric all B or above. `severity × reality`: nothing here is REAL at Major severity or above, so the verdict does not move below the gaps.

### Recommended next steps

Everything below is outside the contract set — **do not edit `proposal.md`, `tasks.md` or `features.json`** (it would invalidate this verdict); disposition these four findings in `verification.md` (applied / ticketed / declined with a reason) or in a follow-up:

1. Extend `test_the_command_exit_status` with non-uniform wall fixtures so the "last window" gate is a named, tested contract (finding 1).
2. Either catch `OSError`/`TimeoutExpired` in `tests_p50` or reword the exit-2 docstring to match what is actually caught (finding 2).
3. Split the table rendering out of `tests_p50` to get under the 40-line rule (finding 3).
4. Re-run the serial comparison at HEAD or record an explicit acceptance that the commit-stamped parity evidence suffices (finding 4).

Then, for the archive itself: `dotf spec archive CI-001-pytest-xdist` once this review is committed — that is what turns the PR's Spec archive gate green (its failure message prescribes exactly this order), so it is not a blocker on the spec's quality.

**Definition of Done, for this review run**: Debt — the four findings above are the list, routed to dispositions, none silently dropped. Knowledge — nothing learned that the findings and lessons don't already carry. Board — skipped as the reviewer; ticket state is the implementer's. Review — PR #3225's checks are triaged above, including the Spec archive gate. Evidence — every claim in this review was produced by a command run in this session; the working tree is clean apart from `specs/CI-001-pytest-xdist/review.md` and the launcher's `review-request.json`.
