---
tags: [spec, tasks, templates]
created: "2026-09-27"
---

# Tasks - APP-CONFIG-016-n8n-pr-path

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `fix/app-config-016-n8n-pr-path` in `~/Projects/kubelab-n8n-pr-path-wt`; #1871 claimed (In Progress, P1) ✓ 2026-09-27
- [x] `proposal.md` complete; the event semantics decided by the operator (forward-only) ✓ 2026-09-27
- [x] Open questions measured, not assumed: `continueOnFail()` in n8n 2.12.3 reads the node, not `options`; Vikunja 1.0.0's `POST /tasks/{id}` is a full update; `GET /tasks/{id}?expand[]=comments` returns the comments under `read_one` ✓ 2026-09-27

## Implementation

Order: the static class guards first, since they need no fixture. Then the node behaviour on real item shapes. Then the graph. The probe comes last, because it can only pass against a deployed workflow.

- [ ] [P] [AC4] Guard `tests/test_n8n_http_error_handling.py`: no `httpRequest` node in any workflow carries `parameters.options.continueOnFail`. `slack-task-capture` is `xfail(strict=True, reason=#1877)`. Red on `multi-forge-sync` (5 nodes)
- [ ] [P] [AC3] Guard `tests/test_n8n_event_reads.py`: no node whose direct predecessor is an `httpRequest` node references `$json.<event field>`. The event fields are read from `Parse Forge Event`'s return keys, not listed by hand. `slack-task-capture` is `xfail(strict=True, reason=#1877)`. Red on `Append PR URL Comment`, `Notify #dev-activity` and `Respond 200`
- [ ] Mutation: commit, restore one original expression in each guard's scope, and see red. Then `git checkout HEAD --`
- [ ] [AC1] Tests for `Extract Matched Task ID` on every item shape (split, wrapped, `{data}`, empty, error) with 0, 1 and 2 results, including `TOOL-0350` against `TOOL-035`. Red against the current node
- [ ] [AC1] Implement it with `$input.all()` and the exact-key rule, sharing the wording of `Extract Issue Task Match`. It emits `matchedTask`, `taskId`, `searchFailed`, and `writeKind` (`none` | `comment` | `done`)
- [ ] [AC2] Tests: `Parse Forge Event` plus the extractor classify each row of the proposal's table from real payloads (Gitea `pull_request` opened/reopened/synchronize/closed with and without `merged`, push, `issue_comment`). Red first
- [ ] [AC2] Implement the classification; the gate after the extractor routes on `writeKind`
- [ ] [AC5] Test: the Update body built from a matched task keeps `title` and `description`, and changes only `done`. Red first, then implement
- [ ] [AC3] [AC4] Graph: the searches get node-level `onError: continueRegularOutput`, and `Find Vikunja Task by Key` gets `alwaysOutputData`. The writes lose the dead option. Each post-request node reads `$('Extract Matched Task ID')`. The success path ends at a new `Respond PR Synced`, and `search-failed` ends at a 502 node. Both guards turn green
- [ ] Update `test_the_pull_request_chain_still_ends_where_it_did` and `test_a_failed_search_is_not_an_empty_search` to the new graph. The latter now describes behaviour that exists
- [ ] `test_n8n_code_node_runtime_render.py` and the v2 filter-shape guard still pass
- [ ] `make test` and `make lint` green

## Probe

- [ ] [AC6] Unit tests in `tests/test_n8n_probe.py` for `signed_pr_merge_closes_its_task`:
  - the happy path;
  - `done` still false;
  - the description erased;
  - no comment;
  - cleanup when the PR step fails.

  Red first.
- [ ] [AC6] Implement it:
  1. create the task through the signed issue event;
  2. send a signed `pull_request` `closed` + `merged` event with the same key;
  3. read back `done`, whether the description is intact, and the comment count via `get_task` with `expand[]=comments`;
  4. delete the task.

  The unsigned probes assert the 200 body names `status`.

## Deploy and verify

- [ ] Tell `kubelab-backup-health-wt-0e` (owner of #1859), then `make import-n8n ENV=staging` from this branch, then `make n8n-probe ENV=staging`
- [ ] PR as draft, triage, then ready. The operator merges
- [ ] Prod: `make import-n8n ENV=prod`, then `make n8n-probe ENV=prod`
- [ ] #1692 and #1659 closed with evidence, or left open with what remains

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

Minimal `features.json` skeleton (drop into `<repo>/specs/APP-CONFIG-016-n8n-pr-path/features.json`):

```json
[
  {
    "id": "APP-CONFIG-016-n8n-pr-path-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
