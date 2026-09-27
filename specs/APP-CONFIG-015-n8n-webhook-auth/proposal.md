---
id: "APP-CONFIG-015-n8n-webhook-auth"
type: spec
status: verifying # draft | implementing | verifying | archived
created: "2026-09-26"
issue: "mlorentedev/kubelab#1712"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# APP-CONFIG-015-n8n-webhook-auth

> **Naming**: file lives at `<repo>/specs/APP-CONFIG-015-n8n-webhook-auth/proposal.md`. `APP-CONFIG-015-n8n-webhook-auth` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #1712: APP-CONFIG-015: multi-forge-sync completes without creating a task — isCreateCandidate is false where the graph says it cannot be -->

The `n8n.kubelab.live/webhook/*` routes have no Authelia in front of them, so each workflow's signature check is the only thing between the internet and the Vikunja and Apprise write nodes. Both halves of that check are broken in n8n 2.12.3, measured by executing the pinned image's own node code (#1712#issuecomment-5842894503). First, Webhook v2 with `rawBody: true` puts the body in `binary.data`, never in `$json.rawBody`, so the HMAC is computed over a re-serialised object and never matches: signed forge events are rejected and no task is ever created. Second, four IF v2 nodes carry v1-shaped `conditions.boolean`, which v2 hands through as a truthy object, so they route every item TRUE, and an unsigned request passes the signature gates. Each defect hides the other, which is why `/task` appeared to work.

## What

- `multi-forge-sync` and `slack-task-capture` compute their HMAC over the exact bytes the sender signed, read from the webhook's binary property, and reject any request whose signature does not match.
- The four IF v2 gates (`Has Task Key & Valid Sig?`, `Found Matched Task in Vikunja?`, `Is Slack Valid?`, `Is Delegable?`) evaluate their condition instead of passing every item. They are migrated to the v2 filter shape (`combinator` plus a `conditions` list), not pinned back to `typeVersion: 1`, so no node is held on a legacy version n8n can retire (operator's decision, 2026-09-26).
- A signed `opened` issue event from the forge creates the Vikunja task it names; an unsigned or wrongly signed request stops at the gate, with nothing written to Vikunja and no notification sent.
- A test fails on any `if`/`filter` node at `typeVersion >= 2` whose parameters are not the v2 filter shape (a Switch v3 keeps its conditions under `rules.values[]`, and the repo has none), and the Code-node tests are fed the item shape Webhook v2 really produces.

## Out of scope

- #1684 (APP-CONFIG-008) AC3 beyond what #1712 needs: retiring `add-to-project.yml` and `bitacora-status.yml` is the next PR.
- #1659, the empty 200 response body; it has a separate probable cause (`responseBody: JSON.stringify(...)`).
- Putting Authelia or an IP allowlist in front of `/webhook/*`: the senders are external forges and Slack, so the signature is the right control.
- Auditing past executions for unsigned requests that got through. That goes on a separate ticket if the Loki/n8n execution history shows any.

## Risks / open questions

- **Which runtime API reads the binary body in a Code node: resolved.** Measured on 2026-09-25 with a local n8n 2.12.3 running the prod Code-node flags: `this.helpers.getBinaryDataBuffer(0, 'data')` and `Buffer` are both available and return the exact bytes. `getBinaryDataBuffer` is the one used, because `Buffer.from(<base64>)` breaks under filesystem binary storage.
- **Slack signs `v0:<timestamp>:<raw body>`.** The raw-body fix applies there too, and the timestamp window check must survive it.
- **Coupling.** Fixing only the gates makes every workflow fail closed, and fixing only the HMAC leaves the gates open, so both land in one PR and are verified together.
- **Replaying the prod fixtures.** Re-delivering `teledyne/openkm-brain#2` writes a real Vikunja task. That is intended, and the fixture is kept for exactly this.

## Acceptance criteria

- [ ] AC1: a correctly signed forge `opened` event, fed to `Parse Forge Event` in the Webhook v2 item shape, gives `isValidSig: true` and `isCreateCandidate: true`, and the same event with a wrong or missing signature gives `isValidSig: false`. Tested in CI.
- [ ] AC2: the same holds for `slack-task-capture`'s signature node with a Slack-signed body, including a stale timestamp being rejected. Tested in CI.
- [ ] AC3: no `if`/`filter` node at `typeVersion >= 2` in `infra/n8n/workflows/` lacks the v2 filter shape; the guard test goes red when one of the four original gates is restored (proven by mutation).
- [ ] AC4, staging then prod: re-delivering `teledyne/openkm-brain#2` creates its task, read back from the Vikunja API.
- [ ] AC5, staging then prod: an unsigned POST to each public webhook stops at its gate, shown in the execution data, with no Vikunja write and no Apprise call.

## References

- Bitácora board: mlorentedev/kubelab#1712 (P1, `security`); follow-ups #1684, #1799.
- Evidence: #1712#issuecomment-5842894503.
- Lesson: `docs/lessons/ci-automation/lesson-467-an-n8n-v2-if-node-with-v1-parameters-always-passes.md` (lesson-467).
- Related ADRs: ADR-050 D3, ADR-066.
