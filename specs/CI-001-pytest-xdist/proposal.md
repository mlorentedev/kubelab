---
id: "CI-001-pytest-xdist"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-11-04"
issue: "mlorentedev/kubelab#3078"   # phase 2: #3111 — repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
owner: manu
wip_override: "owner-directed: #3078 is the critical path of every kubelab PR (fleet CI audit, ci-workflows#8 S4); shortening it speeds up finishing the 14 active specs (14 active, limit 10, 2026-11-04)"
---

# CI-001-pytest-xdist

> **Naming**: file lives at `<repo>/specs/CI-001-pytest-xdist/proposal.md`. `CI-001-pytest-xdist` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #3078: Tests takes 27 minutes in one serial pytest process -->

`ci.yml / Tests` is the critical path of every kubelab pull request: 28.6 min p50, of which `make test` is 27.3 min, because one `pytest` process runs every test file in turn. It is about 40% of all job-minutes across the fleet (ci-workflows#8, ADR-001 practice S4, baseline in ci-workflows `docs/audits/2026-11-ci-baseline.md`).

## What

`make test` runs the suite across every available CPU with `pytest-xdist` (`-n auto --dist loadfile`). Each test file runs on one worker, in order, so module-scoped fixtures behave as in a serial run. Tests that shared state across workers (repo paths, released ports, per-worker temp names) are fixed in the test, not deselected. Coverage is combined across workers by pytest-cov, and the figure equals the serial one on the same commit. The required check `Tests` keeps its name and its contents.

### Phase 2: shards (#3111)

`-n auto` alone took CI's pytest to 13m40s, still over AC2. The suite is split across three runners, by whole test file, balanced by per-file durations measured on CI and committed (`tests/shard_durations.json`). Every shard collects the whole suite and keeps the files assigned to it, so all three compute the assignment from the same input. A file the record does not know weighs the record's mean and still lands in exactly one shard. Each shard uploads its coverage data, and the `Tests` job combines them, then runs lint, types, `validate-sync` and Ansible as before. `Tests` keeps its name and runs `if: always()`, failing when any shard did not succeed, because a required check that is skipped reads as passed. Whole files, not pytest-split: its algorithms split by test, which would cut a module-scoped fixture across runners, the failure `loadfile` was chosen to prevent (lesson-710). Measured on CI (run 41970560974): 2677s over 516 files; the slowest file, `test_monitoring_integration.py`, is 277s, so three shards are bounded by balance rather than by one file.

## Out of scope

- Splitting lint, types and `validate-sync` into their own jobs: those jobs would not be required checks, so gating would be lost until the branch-protection declaration changes (two-PR migration, ADR-042). Follow-up ticket.
- Refreshing the durations record automatically: a stale record costs balance, never correctness. Refresh with `make test-durations` and commit.
- `--dist loadgroup` with `xdist_group` markers: a silent no-op on pytest 9.2 with pytest-xdist 3.8.0 (pytest-dev/pytest-xdist#1407, lesson-712). Revisit on the next xdist release.
- Single-file pytest targets in the Makefile (`test-*-live`, `mutate`): they stay serial.

## Risks / open questions

- Hidden shared state (host ports, Docker names, files in the repo, module globals). Mitigation: run `--dist loadfile`, then `--dist load` twice, check `git status` after each, and group whatever fails.
- Coverage drift: workers start coverage later than the serial engine, so code imported by `conftest.py` at import time may be counted differently. Mitigation: compare `line-rate`/`branch-rate` in `coverage.xml`, not the rounded total.
- Nested `pytest` runs inside tests inherit `addopts`; `-n auto` therefore lives in the `make test` target, not in `addopts`.
- `ubuntu-latest` has 4 vCPU, so stragglers decide whether 10 minutes is reached; the evidence is this PR's own CI run.

## Acceptance criteria

- [x] AC1: the same number of tests passes, with the same coverage figure, as a serial run on the same commit (locally: serial vs xdist; in CI: base commit's `Tests` vs this PR's). ✓ 2026-11-04
- [x] AC2: `Tests` p50 is 10 min or less, measured over 20 pull request runs (verified after merge). ✓ 2026-11-09
- [x] AC3: tests that cannot run in parallel are grouped (by file, `--dist loadfile`) or fixed, never deselected; the default marker expression is unchanged and no `--deselect`/`--ignore` is added. ✓ 2026-11-04
- [x] AC4: the required check name `Tests` does not change. ✓ 2026-11-04
- [x] AC5 (#3111): each shard runs a disjoint set of test files and their union is the whole default selection, including a file the durations record does not know (committed test). ✓ 2026-11-05
- [x] AC6 (#3111): the combined coverage `TOTAL` row equals a single-runner run on the same commit. ✓ 2026-11-05
- [x] AC7 (#3111): `Tests` fails when any shard fails, is cancelled or is skipped (committed test on `ci.yml`). ✓ 2026-11-05

## References

- Bitácora board: mlorentedev/kubelab#3078
- Fleet audit: mlorentedev/ci-workflows#8
- Related ADR: ADR-042 (required check renames), ADR-030 (CI runners)
