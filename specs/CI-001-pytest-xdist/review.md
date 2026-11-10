---
spec: "CI-001-pytest-xdist"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "e86ed7fc8918eadebb9e8a7fecc819630ead890b"
reviewer: "claude-sonnet-5-5"
date: "2026-11-09"
---

## Adversarial review

**Scope**: CI-001-pytest-xdist (mlorentedev/kubelab#3078). The review covers PR #3225 and the two merged PRs it builds on, #3098 and #3124.
**Sources**: specs/CI-001-pytest-xdist/{proposal,tasks,verification}.md and features.json; the diff of origin/master...e86ed7fc (ci_timing.py, tools.py, test_ci_timing.py, Makefile, lesson-728); .github/workflows/ci.yml; GitHub Actions REST data, read-only.

### Spec and task alignment

- **features.json:** the verification commands for f1 to f6 all exit 0. ruff, ruff format, mypy and ruff C901 at 10 are clean on the new files.
- **AC3, AC4 and AC7** were checked against the code:
  - The Makefile `test` recipe carries no option that deselects tests.
  - The `ci.yml` job keeps `name: Tests`.
  - The `Tests` job has `needs: test-shards` and `if: always()`. Its first step exits 1 unless the shards' result is `success`.
- **AC1, AC5 and AC6** rest on the CI figures in verification.md, and those figures add up. 3453 + 2932 + 2872 = 9257, which is master's 9243 plus 14 new tests. The combined TOTAL equals master's.
- **AC2:** the operator accepted the p50 over the last 20 PR runs (8.6 min) on 2026-11-09. The decision is recorded honestly: verification.md and tasks.md give all three windows and point to #3223 and lesson-728. I recomputed the figures from the REST data:
  - The first 20 samples give 15.41 / 6.76 / 3.48 / 2.83 (wall / slowest shard / wait / skew), which matches the record exactly.
  - The last 20 give 8.68. Newer runs have arrived since the recorded 8.6.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test | Fix location |
|---|---|---|---|---|---|---|
| Minor | REAL | metric definition | Wall time starts at the first shard's start, so the first shard's queue is invisible. | First 20 runs: the queue p50 is 4.18 min. Counted from run creation, that window's p50 is 22.1 min. | UNTESTED | code + tests |
| Minor | REAL | reruns | After a rerun, `/runs/{id}/jobs` returns jobs from more than one attempt. | Run 42674176075 mixes jobs from attempts 1 and 2. | UNTESTED | code |
| Minor | REAL | selection bias | Runs cancelled while queued are excluded, and they cluster in saturated windows. | 24 of 176 runs were cancelled, 12 of them in the first 45. | UNTESTED | docs |
| Minor | REAL | CLI contract | The CLI's exit codes and the under-sampling path are untested. Under-sampling exits 0. | tools.py tests-p50 | UNTESTED | tests + code |
| Minor | REAL | design inconsistency | The exit status gates on the last window, which was chosen after seeing the numbers. | ci_timing.py docstring against tools.py | UNTESTED | code or docs |
| Minor | REAL | doc consistency | Lesson-728 gives 15.2, but verification.md gives 14.2. | lesson against verification.md | n/a | lesson |
| Minor | REAL | decomposition | The aggregate job's own run time is not in any column. | Its p50 is 1.52 min. | UNTESTED | code |
| Minor | SPECULATIVE | #3223 | The ticket's burst hours look like a timezone slip. | REST run times | n/a | ticket |
| Minor | SPECULATIVE | input handling | `--since` is not validated. | ci_timing.py | UNTESTED | code |

### Evaluator rubric

| Dimension | Grade | Rationale |
|---|---|---|
| Correctness | B | The recorded numbers reproduce. The start point and the rerun handling are defects, but they do not change AC2. |
| Verification | B | The measurement can be reproduced, but no output was recorded for the lint and types checks. |
| Scope | A | The diff matches the proposal and the tasks. |
| Reliability | C | The CLI is untested, under-sampling exits 0, and reruns are not handled. |
| Maintainability | A | CC is 10 or less, with types and docstrings. |
| Handoff-readiness | B | Lesson-728 has a figure mismatch. |

### Verdict

PASS WITH GAPS

### Recommended next steps

Every item is outside the contract set. The implementer gives each one a disposition in `verification.md`.
