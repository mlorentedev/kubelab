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
- [ ] AC2 (p50 of 10 min or less over 20 PR runs): not met by this PR alone. The pytest step went from 26m43s to 13m40s. Sharding is tracked in #3111; measure after it lands.
- [x] AC3 (grouped, never deselected): `tests/test_pytest_parallel_config.py` checks that the `--dist` mode keeps a file on one worker in order, by running it, and that the default marker expression is unchanged with no `--deselect`/`--ignore`/`-k`.
- [x] AC4 (check name unchanged): `ci.yml` job `name: Tests` untouched (features f3).

## Test status

- Test suite: `make test` locally 8929 passed in 5m18s (serial 17m36s); CI `Tests` green on `d2e92f4c`.
- No regressions: the failure set is identical to serial on base and final commits.

## Decisions made during implementation

- `--dist loadfile`, not `loadgroup`: on pytest 9.2 with pytest-xdist 3.8.0, `loadgroup` silently ignores `xdist_group` (pytest-dev/pytest-xdist#1407). lesson-712.
- The xdist options live in the `make test` recipe, not `addopts`: nested pytest runs inside tests inherit `addopts`.
- `-n auto` over `-n 8`: oversubscribing 4 vCPU was slower (17m05s).
- Shared state fixed in place, not grouped: repo writes (wiki generator), released ports, per-worker temp names, and an assertion sensitive to path length.
- Splitting lint/types/validate-sync out of `Tests` deferred to #3096, because only `Tests` is a required check.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ci-automation/lesson-712-xdist-loadgroup-ignores-every-group-on-pytest-9-2.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: a test-runner option, reversible in one line, with no contract change
- [x] New pattern candidate for `00_meta/patterns/`? no: one project so far; revisit if the fleet's other Python repos adopt xdist under ci-workflows#8

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/CI-001-pytest-xdist/` -> `specs/archive/CI-001-pytest-xdist/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
