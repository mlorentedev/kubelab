---
tags: [spec, tasks, templates]
created: "2026-09-29"
---

# Tasks - AUTH-014-idp-groups-drift

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `fix/auth-014-idp-groups-drift`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

- [x] [AC1] [AC3] Failing tests: `idp_groups_drift` compares the rendered and the live users database by groups only (differ, missing, extra, equal), and no hash reaches a finding
- [x] [AC1] [AC3] Implement `idp_groups_drift` (pure) and the live reader (`kubectl` on the env's spoke, decoded in-process)
- [x] [AC2] Failing tests: `reconcile` with a stale user edits and revokes nothing for them, reports `drift` naming the command; a stale break-glass user still reads `refused`
- [x] [AC2] Implement the `stale` exclusions in `reconcile`
- [x] [AC4] [AC3] Failing test: `review_env` runs the IdP check first, passes `stale` on, turns an unreadable Secret into `authelia failed`, and logs no hash
- [x] [AC4] Wire it into `review_env`
- [x] Docs: module docstring, runbook `identity-tier-change.md` (the "cannot see it yet" line)
- [x] [AC5] Live: `make auth-review ENV=staging` and `ENV=prod`, rc=0, `authelia ... ok`

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test ✓ 2026-09-30
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command ✓ 2026-09-30
- [x] Type checks pass ✓ 2026-09-30
- [x] Lint passes ✓ 2026-09-30
- [x] No unrelated changes in the diff (no scope creep) ✓ 2026-09-30
- [x] `verification.md` filled in ✓ 2026-09-30
- [x] PR opened referencing this spec folder ✓ 2026-09-30

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/AUTH-014-idp-groups-drift/features.json`):

```json
[
  {
    "id": "AUTH-014-idp-groups-drift-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
