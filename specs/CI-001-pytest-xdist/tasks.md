---
tags: [spec, tasks, templates]
created: "2026-11-04"
id: "CI-001-pytest-xdist"
type: spec-tasks
status: active
owner: manu
---

# Tasks - CI-001-pytest-xdist

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feat/issue-3078-pytest-xdist`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

- [x] [AC1] Measure the serial suite on the base commit (count, failure set, `coverage.xml` covered lines/branches, duration)
- [x] [AC3] Write failing guard: `make test` runs `-n auto` with a `--dist` mode proved by a nested run to keep a file on one worker in order, addopts keep `not e2e and not infra`, no `--deselect`/`--ignore`/`-k` (`tests/test_pytest_parallel_config.py`)
- [x] [AC1] Add `pytest-xdist`, put the options in the `make test` recipe
- [x] [AC1] Run `--dist loadfile`, then per-test distribution twice; compare failures, coverage and ignored files with the serial run
- [x] [AC3] Fix the shared state found: `WikiGenerator.wiki_docs_path` follows `project_root`; barrier probe files named per worker; Docker picks the CoreDNS host port; the refused-port test keeps its socket bound
- [x] Found `loadgroup` is a no-op on pytest 9.2 (xdist#1407); switched to `loadfile`
- [x] Fixed `test_restore_drill.py` assertion broken by logger wrapping under the longer xdist basetemp
- [x] Lessons `lesson-710-*`, `lesson-712-*`
- [x] [AC1] Serial vs parallel on the final commit, locally and in CI
- [ ] [AC2] p50 over 20 PR runs: needs sharding (#3111)
- [x] [AC4] `Tests` stays the required check name (unchanged job `name:`)

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/CI-001-pytest-xdist/features.json`):

```json
[
  {
    "id": "CI-001-pytest-xdist-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
