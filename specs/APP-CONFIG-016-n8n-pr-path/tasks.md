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

- [x] [P] [AC4] Guard `tests/test_n8n_http_error_handling.py`: no `httpRequest` node in any workflow carries `parameters.options.continueOnFail`. `slack-task-capture` is `xfail(strict=True, reason=#1877)`. Red on `multi-forge-sync` (5 nodes) ✓ 2026-09-27
- [x] [P] [AC3] Guard `tests/test_n8n_event_reads.py`: no node whose direct predecessor is an `httpRequest` node references `$json.<event field>`. The event fields are every key a Code node returns, read from the code. `slack-task-capture` is `xfail(strict=True, reason=#1877)`. Red on `Append PR URL Comment`, `Notify #dev-activity`, `Respond 200`, and agent-dispatcher's `Respond 200` (fixed in scope) ✓ 2026-09-27
- [x] Mutation: committed, restored `$json.taskId` in `Append PR URL Comment` and an `options.continueOnFail`, each guard went red, then `git checkout HEAD --` ✓ 2026-09-27
- [x] [AC1] Tests for `Extract Matched Task ID` on every item shape (split, wrapped, `{data}`, empty, error) with 0, 1 and 2 results, including `TOOL-0350` against `TOOL-035`. Red against the current node ✓ 2026-09-27
- [x] [AC1] Implement it with `$input.all()` and the exact-key rule. It emits `taskId`, `hasMatchedTask`, `updateBody` and `comment`, and throws on an error item (the proposal's amendment replaces `searchFailed` and the 502 node) ✓ 2026-09-27
- [x] [AC2] Tests: `Parse Forge Event` classifies each row of the proposal's table from real payloads (Gitea `pull_request` opened/reopened/synchronized/edited/closed with and without `merged`, GitHub `synchronize`, push, `issue_comment`, a review comment). Red first ✓ 2026-09-27
- [x] [AC2] Implement the classification in `Parse Forge Event` (`prWriteKind`, `isTrackedPrEvent`); `Is Tracked PR Event?` gates the search and `Is PR Merged?` routes to the state write ✓ 2026-09-27
- [x] [AC5] Test: the Update body built from a matched task equals the task with only `done` changed. Red first, then implement ✓ 2026-09-27
- [x] [AC3] [AC4] Graph: the create-path searches get node-level `onError: continueRegularOutput`; `Find Vikunja Task by Key` gets `alwaysOutputData` and no `onError`. The writes lose the dead option. Each post-request node reads `$('Extract Matched Task ID')`. The success path ends at a new `Respond PR Synced`. Both guards turn green ✓ 2026-09-27
- [x] `test_the_pull_request_chain_still_ends_where_it_did` replaced by `test_the_issue_fork_hands_everything_else_to_the_pull_request_path`; `test_a_failed_search_is_not_an_empty_search` now describes behaviour that exists ✓ 2026-09-27
- [x] `test_n8n_code_node_runtime_render.py` and the v2 filter-shape guard still pass ✓ 2026-09-27
- [x] `make test-fast`, `make lint` and `make type` green (after rebasing on #1875, which fixed the lesson counters) ✓ 2026-09-27

## Probe

- [x] [AC6] Unit tests in `tests/test_n8n_probe.py` for `signed_pr_merge_closes_its_task`: the happy path, `done` still false, the description erased, no comment, an answer other than `done`, and cleanup when the PR delivery fails. The probe's own merge event is run through the workflow's `Parse Forge Event`. Red first ✓ 2026-09-27
- [x] [AC6] Implement it: create the task through the signed issue event (key `PROBE-MERGE-<epoch>`, its own AREA), send a signed `pull_request` `closed` + `merged` event with the same key, read back `done`, a digest of the description and the comments naming the PR (`GET /tasks/{id}/comments`), then delete the task in `finally`. The unsigned forge probes assert `status: ignored`. Mutation: dropping the description check turns its test red ✓ 2026-09-27

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
