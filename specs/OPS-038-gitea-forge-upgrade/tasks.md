---
tags: [spec, tasks, templates]
created: "2026-10-16"
---

# Tasks - OPS-038-gitea-forge-upgrade

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [ ] Branch created from main: `feat/OPS-038-gitea-forge-upgrade`
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

> PR 1 is the rehearsal (image pin on a branch, drill, probes); PR 2 is the live upgrade. No live change before the rehearsal is green and the peers have the window.

- [ ] [AC1] Pin the candidate image `gitea/gitea:1.27.3` in `common.yaml`; extend `tests/test_gitea_actions_runner.py` or the version-pin test so the pin and the drill read the same key
- [ ] [AC1] Run `make backup-drill-gitea ENV=prod` from the branch (candidate image on the restored snapshot, no network); record the outcome
- [ ] [P] [AC2] Add `PUBLIC_URL_DETECTION` to the templated `app.ini` and run `gitea doctor check --all` inside the drill container; fail on any deprecated key
- [ ] [P] [AC3] Write the API contract probe (issue comment, issue and pull create/edit) and run it inside the drill container with a token minted there
- [ ] [P] [AC4] Probe the OIDC callback and `update-oauth --id N` against the restored copy
- [ ] [AC5] Probe the repo `PATCH` merge settings with the `ensure_settings` read-back, and the PR-Agent app against the scratch server
- [ ] [AC6] Check `generate-runner-token` and act_runner 0.2.13 against the scratch server; if it fails, sequence OPS-034 first
- [ ] [AC9] Write `docs/runbooks/gitea-upgrade.md` (rehearsal, rollback by snapshot restore, window) and a lesson
- [ ] [AC7] Tell `review-cli-119-8d`, `feat-2550-lane-reconcile-47`, `fix-bug-sweep-fc` the window; fresh `make backup-node NODE=bee ENV=prod`; `make provision NODE=bee ENV=prod TAGS=gitea`; re-run for `changed=0`
- [ ] [AC8] Measure the cancellation live with two quick pushes; record on #2375; add `concurrency` to forge workflows if none declares it

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

Minimal `features.json` skeleton (drop into `<repo>/specs/OPS-038-gitea-forge-upgrade/features.json`):

```json
[
  {
    "id": "OPS-038-gitea-forge-upgrade-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
