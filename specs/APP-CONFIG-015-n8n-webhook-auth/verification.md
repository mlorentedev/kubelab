---
tags: [spec, verification, templates]
created: "2026-09-26"
---

# Verification - APP-CONFIG-015-n8n-webhook-auth

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 -> `941f1da4` / `tests/test_n8n_multi_forge_sync.py` (red 4, then green), on the item captured from `n8nio/n8n:2.12.3` (`95d48925`)
- [x] AC2 -> `11821e6c` / `tests/test_n8n_slack_capture.py` (red 3, then green), including `test_stale_timestamp_fails_closed_even_when_correctly_signed`
- [x] AC3 -> `efcc992f` / `tests/test_n8n_filter_nodes_v2_shape.py`; mutation: restoring `Is Slack Valid?` fails 2 tests
- [x] AC4 staging -> `make n8n-probe ENV=staging` 2026-09-27, after the staging-minted token (`39d83b95`, #1699): the signed `opened` event answered 201, task 7 `PROBE-1790476108: n8n webhook probe` was read back from Vikunja and deleted. The first run with the new token found one more defect: the 201 carried no `taskId`, because `Respond Task Created` read the notice's `$json` (fixed in `d1e22157`; the probe now also deletes a task found by its key when no id comes back, `28db0ef4`)
- [ ] AC4 prod -> pending merge
- [x] AC5 staging -> `make n8n-probe ENV=staging` 2026-09-27, run twice. Second run: executions 53-55, same result. First run: unsigned forge (execution 45) and wrong-secret forge (46) stop at `Has Task Key & Valid Sig?`; unsigned Slack (47) stops at `Is Slack Valid?`; in each, nothing reached the gate's TRUE output and no `httpRequest` node ran. Unauthenticated agent-dispatcher: HTTP 403 and no execution.
- [ ] AC5 prod -> pending merge

## Test status

- Test suite: `make test` -> 2772 passed, 15 skipped, 1 xfailed (2026-09-26, before the probe); `tests/test_n8n_probe.py` 20 passed
- Live: `make n8n-probe ENV=staging` (above): `[SUCCESS] n8n webhook probe passed`
- No regressions in existing test suite: yes

## Decisions made during implementation

- The IF gates were migrated to the v2 filter shape rather than pinned back to `typeVersion: 1` (operator, 2026-09-26).
- AC4/AC5 are probed by a codified `make n8n-probe`, not ad-hoc requests (operator, 2026-09-26). It judges n8n's execution record, not the HTTP status: Slack acknowledges before its gate, so its status says nothing.
- A signed Slack probe is not included: AC4 is the forge path, and a signed Slack command would POST to a `response_url` the probe cannot own. AC2's unit tests cover the Slack signature.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/APP-CONFIG-015-n8n-webhook-auth/` -> `specs/archive/APP-CONFIG-015-n8n-webhook-auth/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
