---
id: "APP-CONFIG-016-n8n-pr-path"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-27"
issue: "mlorentedev/kubelab#1871"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# APP-CONFIG-016-n8n-pr-path

> **Naming**: file lives at `<repo>/specs/APP-CONFIG-016-n8n-pr-path/proposal.md`. `APP-CONFIG-016-n8n-pr-path` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

No pull request has ever updated its Vikunja task. `multi-forge-sync`'s PR path reads the search result wrongly, so it never finds a match. Even with a match, three later nodes would read the wrong item, the write would erase fields of the task, and a failure would halt the execution without answering. Prod's retained history (2026-09-23 to 2026-09-27) shows 96 signed deliveries entering this path and none leaving it (#1712 verification). ADR-066 D4 promises this path, and until it works the retired GitHub board has no replacement for "this PR closed that ticket" (#1684, then #1799).

## What

A signed `pull_request` event whose title or branch carries a task key reaches that exact task and moves it only forward (ADR-066 D4, "monotonic"), per the operator's decision of 2026-09-27:

| event | Vikunja write | answer |
|---|---|---|
| `pull_request` `opened` / `reopened` | one comment linking the PR; state unchanged | 200 `{status: "linked", taskKey, taskId}` |
| `pull_request` `closed` with `merged: true` | `done: true`, plus a comment | 200 `{status: "done", taskKey, taskId}` |
| push, `issue_comment`, `synchronize`, `edited`, closed without merge | none | 200 `{status: "ignored", reason}` |
| no task with that exact key | none | 200 `{status: "no-task", taskKey}` |
| search failed (401, timeout) | none | 502 `{status: "search-failed"}` |

Mechanically:

1. **The search.** `Extract Matched Task ID` reads `$input.all()` and matches the key exactly: `TOOL-035` never matches `TOOL-0350`. It reuses the rule `Extract Issue Task Match` already has (#1692). `Find Vikunja Task by Key` emits an item on zero results (`alwaysOutputData`), so no-match answers instead of ending silently.
2. **The write.** Vikunja 1.0's `POST /tasks/{id}` is a full update: `Task.updateSingleTask` clears description, priority, dates and colour whenever the body omits them, and the handler validates `title` as non-empty. So `{done: true}` alone either fails validation or wipes the task. The write sends the task as the search returned it, with only `done` changed. The field-scoped `POST /tasks/bulk` needs a token permission (`tasks.update_bulk`) that neither environment's token has.
3. **Reading the event.** Every node after a Vikunja or Apprise request reads the event from `$('Extract Matched Task ID')`, never from `$json`, which by then holds the previous request's response. This is the #1864 defect class.
4. **The answer.** The success path gets its own Respond node, so the body says what happened (#1659 AC1). `Respond 200` stays for the rejections, whose `$json` is correct.
5. **Dead config.** `parameters.options.continueOnFail` does nothing in n8n 2.12.3: `continueOnFail()` reads only the node-level `onError` or `continueOnFail`. Every such option in this workflow is replaced with the intent it was written for:
   - the searches continue on error, and their code nodes already branch on `error`;
   - the writes fail loudly, so the forge records a failed delivery.

   The create path's two searches change behaviour too: until now a 401 halted the run, and now it reaches the `searchFailed` branch its tests describe.

## Out of scope

- The `In Review` bucket move on `opened` (#1687). It needs the Kanban view's bucket ids, a separate design.
- `slack-task-capture`, which has the same three defect classes: #1877 (APP-CONFIG-017). The class guards added here mark that workflow `xfail(strict=True, reason=#1877)`.
- Which task a PR attaches to when its title and branch carry different keys. The extractor's precedence is unchanged.

## Risks / open questions

- **Read-modify-write race.** A human editing the task between the search and the write loses that edit. The window is milliseconds and the path runs only on merge or open. Accepted.
- **Search result completeness.** The write assumes `GET /tasks?s=` returns full task objects (description, assignees, dates). The live probe reads the task back after the write and checks that its description survived, so this is measured rather than assumed.
- **Repeated deliveries.** A redelivered `opened` event adds a second comment. The forge redelivers only on a manual retry. Accepted, and noted in the probe's cleanup.

## Acceptance criteria

- [ ] **AC1** `Extract Matched Task ID`, run on n8n's item shapes (split items, a wrapped array, `{data}`, the `alwaysOutputData` empty item, the error item), resolves the exact-key task for 0, 1 and 2 results, never a substring match. It flags a failed search as failed, not as no match.
- [ ] **AC2** Only the events in the table write. A static test pins which Parse outputs route to a write, and the event classification is executed on real payloads for every row.
- [ ] **AC3** No node downstream of an `httpRequest` node reads an event field from `$json`. A static class guard runs over every workflow in `infra/n8n/workflows/`, and `slack-task-capture` is `xfail(strict=True)` against #1877.
- [ ] **AC4** No `httpRequest` node carries `parameters.options.continueOnFail`. The same class guard applies, with the same `xfail` for `slack-task-capture`.
- [ ] **AC5** The write body carries the searched task with only `done` changed. It is executed in a test: the output keeps `title` and `description`.
- [ ] **AC6** `make n8n-probe` gains a signed PR probe. It creates a task with a description, sends a signed `pull_request` `closed` + `merged` event carrying its key, and reads the task back: `done` is true, the description is intact, and a comment links the PR. It then deletes the task. The unsigned probes also assert the 200 body names `status` (#1659 AC1). Staging, then prod.

## References

- Bitácora: #1871; folds in #1692 (same node) and #1659 AC1 (same Respond node)
- ADR-066 D4 (monotonic transitions); lesson-467 (n8n item shapes); APP-CONFIG-015 (`specs/archive/` once archived)
- Vikunja 1.0.0 source: `pkg/models/tasks.go` `updateSingleTask`; `pkg/models/api_routes.go` (`_bulk` permissions)
