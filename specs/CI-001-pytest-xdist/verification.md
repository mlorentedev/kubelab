---
tags: [spec, verification, templates]
created: "2026-11-04"
id: "CI-001-pytest-xdist"
type: spec-verification
status: active
owner: manu
---

# Verification - CI-001-pytest-xdist

## Evidence

- [x] AC1 (same count, same coverage). Local, commit `d2e92f4c`: serial `pytest` and `make test` both 8929 passed, identical 34-item failure set (macOS environment, also present on base `98eef0d0`), 15706/20330 lines, 4276/6064 branches. CI: master `98eef0d0` 9198 passed / 33 skipped, TOTAL 20328/4624/6064/550; PR run 41954054691 9203 passed (+5 new tests) / 33 skipped, TOTAL 20330/4624/6064/549. The +2 statements are the `wiki_docs_path` property. The -1 partial is the wiki README-less branch, now hit deterministically.
- [x] AC2 (p50 of 10 min or less over 20 PR runs): `make tests-p50 SINCE=2026-11-05T08:13:42Z` (the merge of 95e0acf), run 2026-11-09 over 139 PR runs whose `Tests` succeeded. p50 in minutes, wall / slowest shard / wait / skew: first 20 = 15.4 / 6.8 / 3.5 / 2.8; last 20 = 8.6 / 7.1 / 0.0 / 0.0; all = 14.2 / 7.1 / 2.0 / 2.5. The suite stays near 7 min in every window. The first window holds the 2026-11-06 burst, when five unattended sessions saturated the hosted runners. The operator accepted AC2 on normal load (last 20) on 2026-11-09. The saturation is recorded as #3223 and lesson-728.
- [x] AC3 (grouped, never deselected): `tests/test_pytest_parallel_config.py` checks that the `--dist` mode keeps a file on one worker in order, by running it, and that the default marker expression is unchanged with no `--deselect`/`--ignore`/`-k`.
- [x] AC4 (check name unchanged): `ci.yml` job `name: Tests` untouched (features f3). Phase 2 keeps it on the aggregate job (`jobs.tests.name`), and the shards are `Tests shard N`.
- [x] AC5 (disjoint, complete): `tests/test_test_shards.py` plans the real suite's files plus a file the record does not know, for 1 to 4 shards, and runs the plugin end to end on a synthetic suite. Locally, the three shards on one tree add up to the single run exactly: 3279+2843+2860 = 8982 passed, 0+17+15 = 32 failed, 64+5+25 = 94 skipped, 2 errors, against 8982/32/94/2 (macOS environment failures, identical sets).
- [x] AC6 (combined `TOTAL`): locally equal, 20362/4619/6070/547 for both. In CI, run 41990181968 (eaa2fdb9) combines 3 files to 20362/4619/6070/548, equal to master `d7b057af`'s single-runner run 41982806229 (20362/4619/6070/548). Tests: 3453+2932+2872 = 9257 passed, 33 skipped, against master's 9243 plus this PR's 14 new tests. `Tests` took 8m46s from the first shard's start to the end of the aggregate job, against 10m50s for master's pytest step alone.
- [x] AC7 (`Tests` fails on a failed shard): `if: always()` plus a first step that exits 1 unless `needs.test-shards.result == success`, both asserted by tests (features f5).

## Test status

- Test suite: `make test` locally 8929 passed in 5m18s (serial 17m36s); CI `Tests` green on `d2e92f4c`.
- No regressions: the failure set is identical to serial on base and final commits.

## Decisions made during implementation

- `--dist loadfile`, not `loadgroup`: on pytest 9.2 with pytest-xdist 3.8.0, `loadgroup` silently ignores `xdist_group` (pytest-dev/pytest-xdist#1407). lesson-712.
- The xdist options live in the `make test` recipe, not `addopts`: nested pytest runs inside tests inherit `addopts`.
- `-n auto` over `-n 8`: oversubscribing 4 vCPU was slower (17m05s).
- Shared state fixed in place, not grouped: repo writes (wiki generator), released ports, per-worker temp names, and an assertion sensitive to path length.
- Splitting lint/types/validate-sync out of `Tests` deferred to #3096, because only `Tests` is a required check.
- Phase 2: the plan's file order reaches the runners only with xdist's `loadscopereorder` off, since `loadfile` otherwise reorders files by test count. The plugin turns it off when sharding, as a measured-order test proves. The barrier probe moved out of `tests/`, where scanners on other workers read it mid-delete. The record was refreshed from run 41990181968, measured under shard conditions.
- Phase 2: whole files per shard, a custom plugin rather than pytest-split, whose algorithms split by test and would build a module-scoped fixture on two runners. Three shards: the slowest file is 277s on CI and the suite sums to 2677s, so three shards are bounded by balance (about 223s of work per 4-vCPU shard), not by one file.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ci-automation/lesson-712-xdist-loadgroup-ignores-every-group-on-pytest-9-2.md (phase 2: docs/lessons/ci-automation/lesson-713-a-sharded-required-check-must-run-when-a-shard-fails.md)
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: a test-runner option, reversible in one line, with no contract change
- [x] New pattern candidate for `00_meta/patterns/`? no: one project so far; revisit if the fleet's other Python repos adopt xdist under ci-workflows#8

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/CI-001-pytest-xdist/` -> `specs/archive/CI-001-pytest-xdist/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
