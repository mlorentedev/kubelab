---
id: kubelab-console
type: architecture
status: active
created: "2026-05-09"
---

# kubelab-console (component spec)

> **Status:** `incubating` in this repository as `apps/console` ([ADR-074](../../adr/adr-074-console-and-rest-surface.md)). Today a read-only queue page is embedded in `apps/api` at `console.kubelab.live` (#3107); it is transitional.
> **Parent:** kubelab
> **Layer:** L1-platform
> **ADRs:** [ADR-074](../../adr/adr-074-console-and-rest-surface.md), [ADR-066](../../adr/adr-066-self-hosted-task-platform.md) (2026-10-20 amendment), [ADR-050](../../adr/adr-050-cross-context-command-center.md), [ADR-071](../../adr/adr-071-idp-branding-substrate.md)

## Problem

The operator's work is spread over GitHub, Gitea, CI, review bots, n8n flows and Slack notices. No one surface shows what needs attention now, the state of each pull request, or what the automations did. The GitHub Project board covers one forge only, and Vikunja duplicated state the forges already hold (ADR-066).

## Solution

The operator cockpit: a frontend app on its own host, behind Authelia, over a read model in the kubelab API.

- **Forge view:** every open issue and pull request across forges, in a dense keyboard-first view styled with the brand. It has tabs, URL-held filters, saved views, pagination and per-source freshness.
- **Pull-request state:** conflicting, CI red, reviewer missing, triage owed, CI pending, draft, ready to merge; merged unreviewed on merged ones.
- **Inbox:** why an item needs the operator now.
- **Notices:** what n8n and the bots send to Slack, read at the source.
- **Automations:** n8n flows, shown on the items they acted on and triggerable by name.
- **Product registry:** a later module (ADR-073 D11). Its provisioning actions open PRs: staging merges unattended, prod waits for a human.
- **Fleet status:** a read-only strip of the homelab and cloud nodes from Headscale, showing each node against its always-on or on-demand class (ADR-028).

Statistics stay in Grafana, and the console links to them.

## Tech stack

| Component | Technology |
|-----------|-----------|
| Frontend | `apps/console`: Astro static + React islands + Tailwind 4, the same toolchain as `web` |
| Serving | nginx (unprivileged, read-only root), image `kubelab-console`, built once and promoted by digest |
| Backend | A module of `apps/api` (forge read model, webhooks, reconcile, outbox), Postgres tenant `api` |
| Origin | `console.kubelab.live`: `/console/` to the API, everything else to nginx, both behind Authelia ForwardAuth |
| Brand | ADR-071 tokens projected by `toolkit sync branding`; Inter and JetBrains Mono self-hosted |
| Tests | Playwright and axe |

## Decisions

| Decision | Choice | Reason | Date |
|----------|--------|--------|------|
| Framework | Astro + React islands + Tailwind 4 | Same toolchain as `web`, so the golden path is distilled from two products (ADR-074 D2) | 2026-11-05 |
| Placement | `apps/console` in this repository, incubating | Product lifecycle; ADR-053 §5 (ADR-074 D3) | 2026-11-05 |
| Backend | Stays in `apps/api` | ADR-057 D5, ADR-066 A2 (ADR-074 D1) | 2026-11-05 |
| Auth | Authelia at the edge, `Remote-User` trusted on the console host only | ADR-074 D6 | 2026-11-05 |
| Framework (superseded) | Astro + React islands, built last | 2026-02-21 sketch; reaffirmed in shape by ADR-074 | 2026-02-21 |

## Milestones

The sequence is ADR-074's "Sequence" section. Delivery is tracked on #2570 (CONSOLE-004) and its successors, not here.

The 2026-02-21 sketch's milestones are superseded:

1. Overview and services.
2. Models and security.
3. Memory and agents.
4. A portfolio kanban.

Its gateway and memory panels lost their sources when ADR-029 absorbed them. The kanban's role is ADR-066's forge view. Cluster and security panels would go into the product registry module if they come back.

## Lifecycle

| Transition | Trigger | Date |
|------------|---------|------|
| → idea | Brainstorm session (IDP dashboard discussion) | 2026-02-21 |
| → spec | ADR-050 gives it its shape | 2026-06-20 |
| → incubating | ADR-074: `apps/console` in this repository | 2026-11-05 |

## Notes

- Kill criteria: ADR-066 A8 (opened on at least 5 of 14 days after it ships, or it reverts). Frontend work is gated on the usage counter showing use.
- Scope creep is the named risk. A panel is added only when its data already exists behind the API.
- Backstage was considered and rejected: too heavy to maintain for a single-developer platform.
- Lighter alternatives (Headlamp, Kubero) cover K8s but not the custom L1 services.

## Separate: Stream G — Knowledge Base (Quartz)

This is not part of the console. It was tracked in this file because both are web frontends of the L1 layer. It is unscheduled and kept here verbatim until it gets its own component doc.

> Stream G (Knowledge Base) task breakdown preserved from previous standalone roadmap. Source of truth for KB-001..007. Read-only web viewer for the Obsidian vault using Quartz, synced via Git cron (5 min). Defense-in-depth: Authelia (access) + Quartz filtering (content).

### Backlog

- [ ] **KB-001**: Create Knowledge Base stack (`infra/stacks/services/core/knowledge-base/`)
  - `compose.base.yml`: nginx:alpine serving Quartz HTML output
  - Sidecar/init container: git clone + `npx quartz build`
  - Cron script: `git pull` + rebuild every 5 min (only if changes detected)
  - `compose.dev.yml`, `compose.staging.yml`, `compose.prod.yml`
- [ ] **KB-002**: Add config to `infra/config/values/common.yaml`
  - Domain: `kb.kubelab.test` / `kb.staging.kubelab.live` / `kb.kubelab.live`
  - Git repo URL for vault
  - Quartz config: published folders/tags whitelist
- [ ] **KB-003**: Configure Quartz content filtering
  - Define folder whitelist (e.g., `10_projects/kubelab/`, `20_areas/engineering/`)
  - Exclude sensitive folders (credentials, personal, private notes)
  - Tag-based filter: only notes tagged `public` or in approved folders
  - Verify: build output contains ZERO sensitive notes
- [ ] **KB-004**: Add Traefik route with Authelia middleware
  - `kb.kubelab.test` → knowledge-base container
  - Authelia SSO required (no anonymous access)
- [ ] **KB-005**: Deploy and verify locally
  ```bash
  toolkit services up knowledge-base
  curl -I https://kb.kubelab.test
  # After auth: vault content visible, graph view works, wikilinks resolve
  ```
- [ ] **KB-006**: Verify sync cycle (edit note → push → 5 min → appears on `kb.kubelab.test`)
- [ ] **KB-007**: Verify security layers
  - Layer 1: unauthenticated request → Authelia redirect (no content leaked)
  - Layer 2: inspect built HTML → no sensitive folders/notes present
  - Verify excluded content is not in search index either

**Done when**: Vault accessible at `kb.kubelab.test` behind Authelia, auto-syncs from Git, graph view and wikilinks work, sensitive content excluded at build time AND access-controlled.
