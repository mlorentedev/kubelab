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

- [ ] [AC3] Traefik route that skips Authelia for `grafana.kubelab.live` `/api/` only with a `Bearer glsa_` token (PR #2373), operator merges
- [ ] [AC2] Hand the Grafana token to the gateway env; a gateway script reads alerts and Loki through the datasource API
- [ ] [AC2] Test: an unreadable source is named in the answer, not skipped

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
