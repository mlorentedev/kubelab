---
tags: [spec, tasks, templates]
created: "2026-11-03"
id: "AUTH-022-agent-forge-identity"
type: spec-tasks
status: active
owner: manu
---

# Tasks - AUTH-022-agent-forge-identity

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `feat/agent-forge-identity`, worktree initialised
- [x] Owner decisions: name `agent: dedalo`, new Bitwarden id, per-repository collaborator (2026-11-03)

## Implementation

- [x] [AC1] Identity, scopes, compose env, bootstrap, playbook vars, mint/record/revoke/assert tasks
- [x] [AC1] `ROTATABLE_TOKENS["agent"]`, `AGENT_SCOPES`, `SECRET_CATALOG` entry
- [x] [AC3] `writers:` in the loader, `collaborators_to_grant` in the plan, `ensure_collaborator` with read-back, CLI reads
- [x] [AC1] [AC3] `tests/test_gitea_agent_identity.py`
- [x] [AC4] `make secrets-copy-gitea-agent-token`; dotfiles registry entry (mlorentedev/dotfiles#3152)
- [ ] [AC2] Provision twice, second `changed=0` (blocked by #3080)
- [x] [AC3] Reconcile apply, then plan no-op ✓ 2026-11-05
- [x] [AC4] Copy into Bitwarden after dotfiles#3152 merges; `dotf secrets verify` ✓ 2026-11-05
- [x] [AC5] Open one PR on `personal/imagesensortool` with the agent token; check its author ✓ 2026-11-05 (#152)

## Closing

- [x] ADR-062 amendment, lesson-707, runbook line
- [x] `verification.md` filled in with live evidence ✓ 2026-11-05
- [x] PR opened referencing this spec folder ✓ 2026-11-03 (#3085)

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/AUTH-022-agent-forge-identity/features.json`):

```json
[
  {
    "id": "AUTH-022-agent-forge-identity-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
