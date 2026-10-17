---
tags: [spec, tasks]
created: "2026-10-16"
---

# Tasks - AI-024-hermes-reach

> One task = one focused commit. Stages are separate PRs, in this order. `[AC<n>]` ties a task to the acceptance criterion in `proposal.md`.

## Setup

- [ ] Branch created from master: `feat/ai024-hermes-reach-spec`
- [ ] `proposal.md` is complete and acceptance criteria are testable
- [ ] Open questions in `proposal.md` that block a stage are resolved before that stage starts

## Implementation

### Stage 1: internet (PR #2365)

- [ ] [AC1] Tavily key in the catalog and SOPS, `web.backend` pinned, per-turn cap, `keyless_rescue` off
- [ ] [AC1] Provision ace2 and prove a cited fetch from Open WebUI while the sandbox has no route out

### Stage 2: cluster state

- [x] [AC3] Traefik route that skips Authelia for `grafana.kubelab.live` `/api/` only with a `Bearer glsa_` token (PR #2373), operator merges ✓ 2026-10-17
- [x] [AC2] PR 2a (#2393): stdio MCP server with four fixed tools (firing alerts, errors per app, log volume per app, recent errors of one app), app from a closed list, window from a closed set, Loki redactor in front ✓ 2026-10-17
- [x] [AC2] PR 2a: test that an unreadable source is named with its reason in the output, never skipped, and that nothing is retried ✓ 2026-10-17
- [x] [AC2] PR 2b: `mcp_servers` entry with a `tools.include` allowlist, `GRAFANA_TOKEN` fed from `hermes_kubelab.grafana_token`, the app list in `common.yaml`, the mount and install task, runbook ✓ 2026-10-17 (#2400)
- [!] [AC2] After 2b merges: provision ace2 from a master-based tree and prove the four tools live through the gateway (that is the stage-2 evidence); the refused write is probed through the public `Bearer glsa_` route on `grafana.kubelab.live`, so it measures the route and the token together, and it is a negative control, not proof the wiring works Blocked by #2417: vault-sync fails on ace2 (MEMORY.md rewritten 0600), which fails the agent_stack provision; no agent_stack task ran, so the Grafana reader is not on ace2 yet.

### Stage 3: changes by pull request

- [ ] [AC4] Check the GitHub token's scopes; restrict to draft PRs; test that merge and a push to master are refused

### Stage 4: the 8-hour report

- [ ] [AC5] Signal script with a persisted watermark, a deterministic signal list and the Loki redactor in front
- [ ] [AC5] Job at 06:00, 14:00 and 22:00 Denver (timezone-aware cron if supported, else fixed UTC), `wakeAgent: false` only when neither a signal nor the action ledger changed
- [ ] [AC5] Fixed template and one proposal file per suggested action in the zone
- [ ] [AC8] Action ledger written by the actions and listed by the report

### Stage 5: the mailbox

- [ ] Measure: `send_message` to an arbitrary address, and an approval answered by email
- [ ] [AC6] Poll script: IMAP `UNSEEN`, persisted watermark, allowlist and `Authentication-Results` enforced in the script, failing closed on a missing header, a foreign authserv-id or a result that is not a DMARC pass aligned with `From`
- [ ] [AC7] Test: mail that arrived while the gateway was down is read once at the next poll
- [ ] [AC6] Three tiers; third-party mail goes to a job with `enabled_toolsets` empty
- [ ] [AC8] Outbound mail over SMTP, logged in the ledger
- [ ] [AC9] Test: no credential in any rendered output, log or note
- [ ] Amend ADR-019; mark AI-012 AC7 superseded; DNS records for the domain by Terraform

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Lint passes
- [ ] No unrelated changes in the diff
- [ ] `verification.md` filled in
- [ ] Runbook updated with the mailbox and the residual risk
