---
tags: [spec, tasks, templates]
created: "2026-06-29"
---

# Tasks - ANSIBLE-028-dev-node

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.

## Setup

- [ ] Branch created from main: `feat/ANSIBLE-028-dev-node`
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] No open questions left in `proposal.md` "Risks / open questions"

## Implementation

> Replace these with the actual steps for this feature. Keep them small (one commit each) and in TDD order.

- [ ] Write failing test for <behavior 1>
- [ ] Implement <module/function> to make it pass
- [ ] Refactor for clarity (extract, rename, dedupe)
- [ ] Write failing test for <behavior 2>
- [ ] Implement to make it pass
- [ ] ...

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

Minimal `features.json` skeleton (drop into `<repo>/specs/ANSIBLE-028-dev-node/features.json`):

```json
[
  {
    "id": "ANSIBLE-028-dev-node-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
