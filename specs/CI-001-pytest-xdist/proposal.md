---
id: "CI-001-pytest-xdist"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-11-04"
issue: "mlorentedev/kubelab#3078"   # repo#NNN — GitHub issue / Project item that tracks this spec
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

`make test` runs the suite across every available CPU with `pytest-xdist` (`-n auto --dist loadgroup`). Tests that share state outside their own `tmp_path` carry an `xdist_group` marker, so each group runs on one worker. Coverage is combined across workers by pytest-cov, and the figure equals the serial one on the same commit. The required check `Tests` keeps its name and its contents.

## Out of scope

- Splitting lint, types and `validate-sync` into their own jobs: those jobs would not be required checks, so gating would be lost until the branch-protection declaration changes (two-PR migration, ADR-042). Follow-up ticket.
- Sharding by duration across a matrix. Only if `-n auto` alone stays over 10 minutes, and as its own PR.
- Single-file pytest targets in the Makefile (`test-*-live`, `mutate`): they stay serial.

## Risks / open questions

- Hidden shared state (host ports, Docker names, files in the repo, module globals). Mitigation: run `--dist loadfile`, then `--dist load` twice, check `git status` after each, and group whatever fails.
- Coverage drift: workers start coverage later than the serial engine, so code imported by `conftest.py` at import time may be counted differently. Mitigation: compare `line-rate`/`branch-rate` in `coverage.xml`, not the rounded total.
- Nested `pytest` runs inside tests inherit `addopts`; `-n auto` therefore lives in the `make test` target, not in `addopts`.
- `ubuntu-latest` has 4 vCPU, so stragglers decide whether 10 minutes is reached; the evidence is this PR's own CI run.

## Acceptance criteria

- [ ] AC1: the same number of tests passes, with the same coverage figure, as a serial run on the same commit (locally: serial vs xdist; in CI: base commit's `Tests` vs this PR's).
- [ ] AC2: `Tests` p50 is 10 min or less, measured over 20 pull request runs (verified after merge).
- [ ] AC3: tests that cannot run in parallel are marked and grouped, never deselected; the default marker expression is unchanged and no `--deselect`/`--ignore` is added.
- [ ] AC4: the required check name `Tests` does not change.

## References

- Bitácora board: mlorentedev/kubelab#3078
- Fleet audit: mlorentedev/ci-workflows#8
- Related ADR: ADR-042 (required check renames), ADR-030 (CI runners)
