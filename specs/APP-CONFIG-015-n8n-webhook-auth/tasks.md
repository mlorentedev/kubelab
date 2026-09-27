---
tags: [spec, tasks, templates]
created: "2026-09-26"
---

# Tasks - APP-CONFIG-015-n8n-webhook-auth

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch: `fix/app-config-015-n8n-webhook-auth` (renamed from `feat/bitacora-to-vikunja` once the scope narrowed to #1712) ✓ 2026-09-25
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-09-26
- [x] No open questions left in `proposal.md` "Risks / open questions": the runtime API was measured on 2026-09-25, and the IF shape was decided on 2026-09-26 ✓ 2026-09-26

## Implementation

Order: the gate guard first, because it is static and needs no fixture. Then the item shape, which both HMAC paths need. Then the two HMAC paths. Nothing is deployed until all three are green together, because the fixes are coupled (proposal, Risks).

- [x] [P] [AC3] Write the failing guard (`tests/test_n8n_filter_nodes_v2_shape.py`): every `if`/`filter` node at `typeVersion >= 2` in `infra/n8n/workflows/*.json` carries `conditions.combinator` and a `conditions.conditions` list. It must go red on exactly the four gates named in the proposal. Red on exactly those four ✓ 2026-09-26
- [x] [AC3] Migrate the four gates to the v2 filter shape, each keeping its original condition (the field and a boolean `true` operator). Also assert per gate that the condition still reads the field it read before, so a correct shape that tests the wrong thing is caught. Executed with n8n 2.12.3's own `executeFilter`: each gate is TRUE for `true` and FALSE for `false` and `undefined` ✓ 2026-09-26
- [x] [AC3] Mutation: commit, restore one original gate, and see the guard go red. Then `git checkout HEAD --` the file. Restoring `Is Slack Valid?` fails 2 tests ✓ 2026-09-26
- [x] [P] [AC1] Capture the Webhook v2 item shape from the pinned `n8nio/n8n:2.12.3` into a fixture, with a script (`tests/fixtures/n8n/capture_webhook_item.py`) rather than by hand. A test asserts the fixture records the same n8n tag as `infra/k8s/base/kustomization.yaml`, so a version bump forces a recapture. The capture posts a JSON body and a form body; both arrive only in `binary.data` ✓ 2026-09-26
- [x] [AC1] Rewrite the `Parse Forge Event` tests on that shape. The harness provides `this.helpers.getBinaryDataBuffer` backed by the fixture's bytes, and drops the `$json.rawBody` string that n8n never produces. Covered: signed `opened` gives `isValidSig` and `isCreateCandidate` true; wrong signature, missing signature and missing binary give `isValidSig` false. Red against the current node (4 failed) ✓ 2026-09-26
- [x] [AC1] Implement: `Parse Forge Event` reads the body with `getBinaryDataBuffer(0, 'data')`, HMACs the Buffer, compares with `timingSafeEqual`, and fails closed with no binary. The `JSON.stringify(body)` fallback is removed ✓ 2026-09-26
- [x] [P] [AC2] The same for `slack-task-capture`'s signature node: tests on the fixture shape with the Slack basestring `v0:<ts>:<raw bytes>`, plus a stale timestamp rejected. Red first (3 failed: delivered bytes, no bytes, tampered) ✓ 2026-09-26
- [x] [AC2] Implement the Slack node the same way, keeping the timestamp window. The `URLSearchParams` rebuild is removed ✓ 2026-09-26
- [x] `test_n8n_code_node_runtime_render.py` still passes: no new `$env` or `require` without the environment declaring it (6 passed) ✓ 2026-09-26
- [x] `make test` green: 2772 passed, 15 skipped, 1 xfailed ✓ 2026-09-26

## Deploy and verify

- [x] [AC4] [AC5] Codify the probes as `make n8n-probe ENV=<env>` (`toolkit/features/n8n_probe.py`), judged from n8n's execution record. The operator chose this over ad-hoc requests on 2026-09-26 ✓ 2026-09-27
- [x] Staging: `make import-n8n ENV=staging` (DB-only, so staging's `targetRevision` did not need to move; the BACKUP-055 lane agreed) ✓ 2026-09-27
- [x] [AC4] Staging: deliver a signed `opened` event and read the created task back from the Vikunja API. Unblocked by a staging-minted token (#1699); the first run then found the missing `taskId` in the 201, fixed in `d1e22157`. Task 7 read back and deleted ✓ 2026-09-27
- [x] [AC5] Staging: send an unsigned POST to each public webhook. Each stops at its gate in the execution data, with no Vikunja write and no Apprise call. `make n8n-probe ENV=staging`: executions 45-47 stop at their gate, agent-dispatcher 403 ✓ 2026-09-27
- [ ] PR, triage, merge by the operator. Then point staging back to `master`.
- [ ] [AC4] Prod: `make import-n8n ENV=prod`, re-deliver `teledyne/openkm-brain#2`, and read its task from Vikunja.
- [ ] [AC5] Prod: the unsigned probes from staging, repeated.
- [ ] If the n8n execution history shows unsigned requests that reached a write node before the fix, file a ticket (proposal, Out of scope).

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

Minimal `features.json` skeleton (drop into `<repo>/specs/APP-CONFIG-015-n8n-webhook-auth/features.json`):

```json
[
  {
    "id": "APP-CONFIG-015-n8n-webhook-auth-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
