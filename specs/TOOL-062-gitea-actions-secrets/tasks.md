---
tags: [spec, tasks, templates]
created: "2026-09-23"
---

# Tasks - TOOL-062-gitea-actions-secrets

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feat/tool-062-gitea-actions-secrets`
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

- [x] [P] Failing test: `forge_actions_secret_name` maps a key path's leaf to the upper-case secret name
- [x] Implement `SecretSpec.forge_actions`, `forge_actions_secret_name`, `secrets_delivered_to_forge()`
- [x] [P] Failing test: no two catalog entries deliver the same name to the same repository; every delivered entry is `prod`-scoped and says what rotating it costs
- [x] Add the four `personal/resume` `GDRIVE_*` catalog entries
- [x] [AC1] [AC4] [AC5] Failing tests for the pure planner: create when absent and valued; report missing SOPS values without pushing; report undeclared live secrets without deleting
- [x] Implement `plan_actions_secrets` in `toolkit/features/gitea_actions_secrets.py`
- [x] [AC3] Failing test: `force=True` re-PUTs every declared secret that holds a value, and none that does not
- [x] Implement the force path
- [x] [AC6] Failing tests: no value appears in the plan, its formatting, or any record's `repr`
- [x] Implement `format_actions_secrets_plan` and `repr=False` on value-carrying records
- [x] [AC2] [AC4] Failing tests for `execute_actions_secrets` against a fake client: PUTs exactly the planned set, records per-secret failures, never calls delete
- [x] Implement `execute_actions_secrets` and `GiteaBasicAuthClient.list_actions_secrets` / `put_actions_secret`
- [x] Wire `toolkit services gitea actions-secrets [--env] [--apply] [--force]`: plan-only by default, exit 1 when apply meets a missing value
- [x] Live, plan-only against prod: the four secrets are listed as missing values until the operator lands them

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test
- [x] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command (f7 pending by design: it is the by-effect check)
- [x] Type checks pass
- [x] Lint passes
- [x] No unrelated changes in the diff (no scope creep)
- [x] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/TOOL-062-gitea-actions-secrets/features.json`):

```json
[
  {
    "id": "TOOL-062-gitea-actions-secrets-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
