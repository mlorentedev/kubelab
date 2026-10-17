---
id: "AI-024-hermes-reach"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-16"
issue: "mlorentedev/kubelab#2364"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Operator decision 2026-10-17: AI-024 is needed now (the 8-hourly report and the mailbox); the active specs it exceeds are in flight. (17 active, limit 10, 2026-10-16)"
---

# AI-024: hermes-kubelab reach

## Why

<!-- from issue #2364: AI-024: hermes-kubelab reach: internet, cluster state, PRs and a mailbox (proposal) -->

hermes-kubelab reads the vault and the alert channels, but it has no internet, no view of the cluster beyond Slack, no way to propose a change to a repository and no mailbox. The operator wants it to work as an operations assistant: research on the web, answer for the cluster's state, open draft PRs, take instructions by email, and hand over an executive draft every eight hours that says what it saw, what it did and what it proposes. Without it the operator watches the channels and the dashboards by hand and applies every follow-up from memory.

## What

Staged, one small PR each; each stage is useful alone.

1. **Internet.** `web_search` and `web_extract` through one pinned backend (Tavily, free tier), run by the gateway, so a turn can cite a source while the sandbox keeps `terminal.docker_network: false` (ADR-068 D2). A per-turn cap bounds the spend. (PR #2365.)
2. **Cluster state.** The Grafana Viewer token reaches the gateway; `grafana.kubelab.live` skips Authelia for `^/api/.*` only, so the token is judged by Grafana. No kubeconfig: the agent's uid is refused private and tailnet networks (#2161).
3. **Changes by pull request.** The existing GitHub token, scoped to draft PRs. The agent cannot merge and cannot push to master.
4. **Periodic report, every 8 hours** (06:00, 14:00, 22:00 Denver, converted to UTC in the cron). A gateway-side script computes a deterministic signal list (alert deltas, Loki error counts per app against the prior window, pod restarts, backup age per node, certificate and credential expiry, disk, open PRs and CI, proposals pending, model spend) and an action ledger; the model only writes prose over it, in a fixed template. One proposal draft per suggested action lands in `80_agents/hermes-kubelab/proposals/`. When nothing changed the job ends silent with `{"wakeAgent": false}`; the daily digest is the heartbeat.
5. **Mailbox `hermes@mlorente.dev`** (Zoho Mail Lite, IMAP and SMTP, its own user). A gateway-side poll script reads `UNSEEN` mail with a persisted watermark, so mail that arrives while ace2 is off is still read at power-on. Three tiers, keyed on the authenticated sender: the operator's addresses give orders; known senders are read and answered with a draft for approval; anyone else is read by a job with `enabled_toolsets` restricted to none and gets no action. Outbound is always logged in the action ledger that the next report lists. Whether it may reach an address outside the tiers without per-send approval is open (see Risks); until measured, the default is approval for any recipient that is not the operator.

## Out of scope

- Opening the sandbox's network (needs its own tailnet identity first).
- Merging, releasing or any prod change by the agent.
- A personal assistant that books travel or makes purchases: it reads third-party content and spends money, so it is a separate profile with its own spec.
- BrightData research (AI-012 AC7): superseded by stage 1 unless the free tier proves too small.

## Risks / open questions

- A Traefik route (#2373) skips Authelia for `/api/` only when the request carries a `Bearer glsa_` token, so Grafana's own authentication is the only gate on that path. An Authelia `bypass` rule was tried first (#2369) and rejected: it cannot see headers, so it also opened Basic credentials (lesson-585). The token stays Viewer-scoped. Prod ingress edit: the operator merges it.
- Hermes's email adapter marks existing mail seen on the first connect of each process, so it cannot be the intake on an on-demand node. To measure: whether `send_message` can address an arbitrary email and needs constraining, and whether an approval can be answered by email.
- Third-party mail is untrusted input to a model that can send mail: the tiers, the restricted toolset and the ledger are the controls. State the residual risk in the runbook.
- Zoho: whether IMAP is blocked at the domain level, the region, and the `Authentication-Results` authserv-id from a real header. The poll script fails closed: a missing header, a different authserv-id or a non-`pass` result drops the message without starting a turn. Operator checks these in the Admin Console. ADR-019 says to cancel Zoho and needs an amendment.
- Spend: every authorized email starts an agent turn. The per-turn web cap bounds searches only and the quiet-period rule bounds the report, not mail, so the poll script also carries a cap on turns per hour; mail beyond it waits for the next poll and is named in the report.
- The model must not be the only line of defense: authorization is enforced in the script, not in the prompt.

## Acceptance criteria

- [ ] A turn from Open WebUI answers a question with a cited web source while a command in the sandbox has no route out.
- [ ] Asked for the cluster's state, the agent answers from Grafana, and says so when a source is unreadable.
- [ ] An unauthenticated request to `grafana.kubelab.live/api/` is answered by Grafana with 401, not redirected to the portal, and the UI still redirects.
- [ ] A draft PR opened by the agent cannot be merged by it, and a push to master is refused.
- [ ] The 8-hour report arrives in Slack with the fixed sections, one proposal file per suggested action, and no report is sent when no signal changed.
- [ ] Mail from the operator's address is answered in-thread; mail that fails authentication starts no turn; mail from any other address is read without tools and triggers no action.
- [ ] Mail that arrived while ace2 was off is read at the next poll, once.
- [ ] Every outbound email and every change the agent made appears in the next report's action ledger.
- [ ] No credential appears in any channel, log, vault note or report.

## References

- Bitácora board: mlorentedev/kubelab#2364
- Related specs: `specs/AI-012-hermes-harness/` (AC7 superseded by this spec's stage 1), PR #2365 (stage 1), PR #2354 (alerts and Grafana token)
- Related ADRs: `docs/adr/adr-068-*` (sandbox network), `docs/adr/adr-019-saas-consolidation-proton.md` (to amend)
- Runbook: `docs/runbooks/hermes-kubelab.md`
