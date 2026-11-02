---
tags: [spec, tasks, templates]
created: "2026-11-01"
---

# Tasks - AI-025

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `feat/ai025-openwebui-assistant` from master
- [x] `proposal.md` complete; AC1 measured (#2915)

## Implementation

PR 1 (web search):

- [x] [AC2] Failing tests: SearXNG service with no port, read-only settings with `json`, key generated on the node, restart on settings change, Open WebUI env (`tests/test_open_webui_web_search.py`)
- [x] [AC2] SearXNG in `compose-webui.yml.j2`, its settings and env templates, role tasks, `common.yaml` pin
- [x] [AC5] `web_search` in `defaultFeatureIds`
- [x] [AC2] Provision ace2 from the branch twice (`changed=0`), then an operator query that needs current information returns cited results

PR 2 (code interpreter and memory):

- [ ] [AC3] [AC5] Failing test, then `code_interpreter` in `defaultFeatureIds`
- [ ] [AC4] Failing test, then `ENABLE_MEMORY_BACKGROUND_REVIEW=true`
- [ ] [AC3] [AC4] Provision, then the operator runs Python in a chat and sees a fact carried to a new chat

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

Minimal `features.json` skeleton (drop into `<repo>/specs/AI-025/features.json`):

```json
[
  {
    "id": "AI-025-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
