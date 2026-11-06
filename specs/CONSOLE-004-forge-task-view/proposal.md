---
id: "CONSOLE-004-forge-task-view"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-10-21"
issue: "mlorentedev/kubelab#2570"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "ADR-066 amendment merged (#2575); the spec gates all CONSOLE-004 code; archiving the obsolete APP-CONFIG-013 needs an independent review and is tracked under #2443 (13 active, limit 10, 2026-10-21)"
---

# CONSOLE-004-forge-task-view

> **Naming**: file lives at `<repo>/specs/CONSOLE-004-forge-task-view/proposal.md`. `CONSOLE-004-forge-task-view` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #2570: CONSOLE-004: forge read/operate console replaces Vikunja and GitHub Projects (ADR-066 amendment first) -->

Issues and pull requests live on GitHub and Gitea, and the only unified view was the GitHub Projects board, which cannot show a Gitea item. Vikunja tried to be that view by copying forge state into its own store, and every amendment of ADR-066 has been a patch to that duplication. Without a view over the forges themselves, tracking stays split between two forges and a third tracker nobody wants to operate. Decided in the ADR-066 amendment of 2026-10-20 (A1 to A8).

## What

A module of `apps/api` (ADR-066 amendment A2), not a new service. Behind Authelia, it adds:

1. **A queue.** Issues and pull requests from Gitea and GitHub, grouped and sorted by state and priority, each with an inbox reason (author, requested reviewer, failing CI, waiting on me). Every row shows when its source was last read, and an unreachable forge is shown as unreachable, never as empty.
2. **Narrow writes.** From a row: create an issue, add or remove a `status:*` or `priority:*` label, assign or unassign, close or reopen. No merge and no review. An action is shown as pending until the forge confirms it.
3. **Slack capture.** `/task create` opens an issue through the same create write, in the repository its `area:` label maps to, or in `knowledge` when none does. Every task is an issue in some repository, and the view stores no item without one. This is CONSOLE-007 (#2586) and lands after the view.
4. **Statistics in Grafana.** Throughput, queue age, time to first review, time with a red CI and items by status, priority and area, plus the health of the view itself. Grafana shows aggregates only and opens no action: the view stays the place to act.

## The console

Decided with the operator on 2026-11-04, after the read model was live and the page still had no address.

- **Address.** `console.kubelab.live` (staging `console.staging.kubelab.live`), declared once as `infra.forge.console_domain`. A host of its own, behind Authelia whole like Grafana or n8n, rather than a path on `api.kubelab.live`: a path made the public API host carry one signed-in corner, held by a Traefik path rule and an Authelia `resources` regex that each failed open alone, and `mlorente.dev` already proxies `/api` to the same Service with no session in front.
- **Served by the api binary for now.** Because that binary also answers the public API host, it serves `/console` only to a request for the console host, and to none when the host is not declared. [ADR-074](../../docs/adr/adr-074-console-and-rest-surface.md) makes that page transitional: the frontend moves to `apps/console` (D1, D2), the API keeps its console surface under `/console/` on the same host (D5), and the embedded page is deleted when `apps/console` serves the same view. The ADR's sequence orders the work from here, and this spec's acceptance criteria are unchanged by it.
- **Who uses it**: the operator, signed in through Authelia. Break-glass is a port-forward to the api Service.

| Use case | Screen | Delivery |
|---|---|---|
| What needs me: review requested, my pull requests with a red CI, assigned to me | Inbox | Reasons in the second slice |
| Triage everything open on both forges by repository, area, priority or text | All | First slice (filter by text) |
| Trust the view: when each forge was read, and whether it is down | Freshness bar on every screen | First slice |
| Set `status:*` or `priority:*`, assign, close or reopen from a row | Row actions | AC2 |
| Capture an issue, repository chosen by `area:` | New issue | AC2, and CONSOLE-007 from Slack |

The first slice is read-only: the page, `GET /console/queue` (open items of the declared sources, newest first, with each source's last read time and reachability) and the access above. Its JSON is open to a `reasons` field on each item, added by the second slice without breaking the page.

```
console.kubelab.live                       [Inbox] [All] [+ New issue]
github:mlorentedev/kubelab read 3 min ago - gitea:personal/resume read 1 min ago
----------------------------------------------------------------------------
INBOX
  review requested  kubelab #3068 PR  fix(api): keep forge deliveries ...
  red CI            kubelab #3041 PR  build(api): x/crypto ...
  assigned          resume  #12       Update CV for ...      [status v][close]
ALL  (filter: repository / area / priority / text)
  P1 status:in-progress  kubelab #2570  CONSOLE-004 ...      [status v][prio v]
```

## Out of scope

Things this PR explicitly does NOT include. Forces a sharp boundary and prevents scope creep.

- Retiring Vikunja and the GitHub Project board (#2587, dotfiles#2846). They start after parity and after the 14 days of A8.
- Merge, review submission and reviewer requests: left out of the first version because of `review-attestation` and the merge grant.
- GitLab, a third adapter added later.
- Grafana as a second interface: no titles of private items and no actions there (ADR-073 D10).
- Automations that fire from the view's events (for example a reminder for a red CI older than two days). They go through the notification fabric (ADR-044) and get their own ticket.

## Risks / open questions

Failure modes, dependencies, and unknowns to clarify before implementation. If any item here is unresolved, do not move to `tasks.md` yet.

- **Where the UI is served**: decided 2026-11-04, see "The console" below.
- **Delivery order.** The pain stops when the view is usable, not when Vikunja is deleted. The read queue over both forges ships first, the narrow writes second, and the retirement waits for parity and A8's 14 days. A8's timebox was widened by the operator to ADR-074's sequence, and the A2 and A8 corrections landed in #2623.
- **GitHub call budget.** The GraphQL secondary limit already cuts sessions short. Reads go through webhooks plus a periodic reconcile, never polling, with a stated hourly call ceiling (#1501).

## Acceptance criteria

Observable outcomes. Each must be testable.

- [ ] **AC1 queue.** With one Gitea organization and one GitHub repository configured, the queue lists issues and pull requests from both with their inbox reason. With a forge stubbed as down, that source is shown as unreachable with its last read time, never as empty.
- [ ] **AC2 writes.** Create, label, assign and close or reopen show as pending until the forge confirms. Create requires a repository: the `area:` label maps to one, declared once in `common.yaml`, and `knowledge` is the fallback. Every write leaves an audit row (who, what, which issue, when). Replaying the same request creates no duplicate. No merge, review or reviewer-request route exists, and a test asserts it.
- [ ] **AC3 access.** Without a credential the API answers 401 and the browser needs an Authelia session. A scoped machine token, kept in SOPS and `SECRET_CATALOG` apart from the operator's session and the read token, is accepted on the create write only and refused on every other route. This is what lets CONSOLE-007 (#2586) call it from n8n.
- [ ] **AC4 budget.** A webhook with an invalid HMAC is rejected. A full reconcile stays under an hourly GitHub call ceiling that the spec fixes (#1501).
- [ ] **AC5 end to end.** On staging, an issue opened on Gitea and one opened on a GitHub repository appear in the queue within a stated bound, and a `status:*` label added from the queue is read back from the forge. Run by a named command (`make test-e2e ENV=staging` or a new probe target), not by hand.
- [ ] **AC6 observability.** Per-source freshness, failed webhook deliveries, reconcile duration and outbox depth are queryable in Grafana, and an alert fires when a source has not been read for longer than a declared bound. Statistics read a view of the read model that carries counts and no titles.
- [ ] **AC7 operations.** The read model, event table and outbox are covered by the existing Postgres backup and a restore is rehearsed once. A runbook covers rebuilding the read model from the forges, restoring from backup and rotating the tokens, and each token's expiry is in the SOPS catalog.

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related ADRs: [ADR-066](../../docs/adr/adr-066-self-hosted-task-platform.md) (amendment A1 to A8), [ADR-074](../../docs/adr/adr-074-console-and-rest-surface.md) (console frontend, its surface and its sequence), [ADR-057](../../docs/adr/adr-057-kubelab-api-boundaries.md) D2 and D5 (one API)
- Related patterns: `00_meta/patterns/<pattern>.md` (if any)
