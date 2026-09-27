---
tags: [spec, verification, templates]
created: "2026-09-26"
---

# Verification - APP-CONFIG-015-n8n-webhook-auth

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 -> #1855 / `tests/test_n8n_multi_forge_sync.py` (red 4, then green), on the item captured from `n8nio/n8n:2.12.3` (`tests/fixtures/n8n/capture_webhook_item.py`)
- [x] AC2 -> #1855 / `tests/test_n8n_slack_capture.py` (red 3, then green), including `test_stale_timestamp_fails_closed_even_when_correctly_signed`
- [x] AC3 -> #1855 / `tests/test_n8n_filter_nodes_v2_shape.py`; mutation: restoring `Is Slack Valid?` fails 2 tests
- [x] AC4 staging -> `make n8n-probe ENV=staging` 2026-09-27, after the staging-minted token (#1864, #1699): the signed `opened` event answered 201, task 7 `PROBE-1790476108: n8n webhook probe` was read back from Vikunja and deleted. The first run with the new token found one more defect: the 201 carried no `taskId`, because `Respond Task Created` read the notice's `$json` (fixed in #1864, where the probe also learned to delete a task found by its key when no id comes back)
- [x] AC4 prod -> after `make import-n8n ENV=prod` from `0b78683a` (2026-09-27): `make n8n-probe ENV=prod` created task 2 `PROBE-1790477749: n8n webhook probe`, read it back and deleted it. Then the real fixture: the operator closed and reopened `teledyne/openkm-brain#2` on the forge. Execution 202 (`closed`) ended at `Respond Issue Handled`, and execution 203 (`reopened`) ran the whole create path to `Respond Task Created`. Vikunja task 3, `APP-CONFIG-014: confirm the create path reaches the board after the runtime fix`, is in project 2 (Bitacora), created 2026-09-27T02:59:57Z. That is the event #1712 was opened for
- [x] AC5 staging -> `make n8n-probe ENV=staging` 2026-09-27, run twice. Second run: executions 53-55, same result. First run: unsigned forge (execution 45) and wrong-secret forge (46) stop at `Has Task Key & Valid Sig?`; unsigned Slack (47) stops at `Is Slack Valid?`; in each, nothing reached the gate's TRUE output and no `httpRequest` node ran. Unauthenticated agent-dispatcher: HTTP 403 and no execution.
- [x] AC5 prod -> `make n8n-probe ENV=prod` 2026-09-27: unsigned forge (execution 198) and wrong-secret forge (199) stop at `Has Task Key & Valid Sig?`, unsigned Slack (200) stops at `Is Slack Valid?`, and the unauthenticated agent-dispatcher call gets HTTP 403 with no execution
- [x] History (proposal, Out of scope) -> prod n8n retains executions from 2026-09-23 onward: 111 for `multi-forge-sync` and `slack-task-capture`. Before the fix, 107 ran through the always-TRUE gate, and all 107 were signed Gitea deliveries (`Go-http-client/1.1`, `personal/resume`). Each ended after the read `Find Task for Issue`, and none reached `Create Task from Issue` or an Apprise node. The only write in the retained history is the probe's own (execution 197). No ticket: nothing unsigned reached a write node in the window that exists. Before 2026-09-23 the executions are pruned, so that period cannot be judged from n8n

## Test status

- Test suite: `make test` -> 2868 passed, 15 skipped, 1 xfailed (2026-09-27, #1864's head)
- Live: `make n8n-probe ENV=staging` and `ENV=prod` (above): `[SUCCESS] n8n webhook probe passed` in both
- No regressions in existing test suite: yes

## Decisions made during implementation

- The IF gates were migrated to the v2 filter shape rather than pinned back to `typeVersion: 1` (operator, 2026-09-26).
- AC4/AC5 are probed by a codified `make n8n-probe`, not ad-hoc requests (operator, 2026-09-26). It judges n8n's execution record, not the HTTP status: Slack acknowledges before its gate, so its status says nothing.
- A signed Slack probe is not included: AC4 is the forge path, and a signed Slack command would POST to a `response_url` the probe cannot own. AC2's unit tests cover the Slack signature.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes, already written as lesson-467 (Webhook v2 raw bytes arrive in `binary.data`; an IF v2 node with v1 conditions is always TRUE). The `$json`-is-the-predecessor defect is held by the test that found it, not a lesson
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no. The fixes restore the declared design and do not change it
- [x] New pattern candidate for `00_meta/patterns/`? no. Judging a webhook by the execution record rather than its HTTP status is n8n-specific so far

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/APP-CONFIG-015-n8n-webhook-auth/` -> `specs/archive/APP-CONFIG-015-n8n-webhook-auth/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
