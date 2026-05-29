---
id: kubelab-console
type: architecture
status: active
created: "2026-05-09"
---

# kubelab-console (component spec)

> **Status:** `spec` — no code yet. Lives here as a design doc until promotion criteria are met.
> **Parent:** kubelab
> **Layer:** L1-platform
> **ADRs:** [ADR-008](../../adr/adr-008-quartz-obsidian-knowledge-base.md)

## Problem

The IDP has no visual convergence point. Services, agents, models, security scans, and operational memory are all accessed through separate CLIs, APIs, and terminal UIs. Hard to demonstrate as an integrated product. No portfolio-level kanban view.

## Solution

Web dashboard that consumes APIs from all L1 platform services and K8s directly. Serves as both the operational control plane and the portfolio showcase. Built with Astro + React islands (consistent with existing web stack, SSR by default, interactive where needed).

A second sub-stream (Stream G — Knowledge Base) is tracked here because both are web frontends in the L1 platform layer, even though the KB is architecturally separate (read-only Quartz over the vault behind Authelia).

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Framework | Astro + React islands |
| Styling | Tailwind CSS |
| API consumption | REST/gRPC from L1 services + K8s API |
| Auth | OAuth2/OIDC (via Authelia, reuse Headscale OIDC) |
| Deploy | K8s Deployment in kubelab cluster |
| KB sub-stream | Quartz (static site generator over Obsidian vault) + nginx:alpine |

## Dependencies

- kubelab L0 (K3s, Traefik, Authelia)
- kubelab-cli L1-1 (config / service catalog data)
- [kubelab-gateway](kubelab-gateway.md) L1-2 (model management panel — note: absorbed into kubelab API per ADR-029)
- [kubelab-memory](kubelab-memory.md) L1-3 (operational timeline / search — note: absorbed into pgvector RAG per ADR-029)
- [kubelab-agents](kubelab-agents.md) L1-4 (agent status, task delegation)
- sec-scan L3-3 (security findings panel)

## Decisions

| Decision | Choice | Reason | Date |
|----------|--------|--------|------|
| Framework | Astro + React islands | Consistent with web stack, zero JS default, interactive where needed | 2026-02-21 |
| Build order | LAST (after all L1 services have stable APIs) | Dashboard without data is an empty shell | 2026-02-21 |
| Purpose | Portfolio showcase + operational tools | Dual purpose justifies the frontend investment | 2026-02-21 |

## Milestones (component-level)

| # | Milestone | Done criteria | Status |
|---|-----------|---------------|--------|
| 1 | Overview + Services | Cluster health, service catalog, deploy history (K8s data only) | [ ] |
| 2 | Models + Security | gateway integration (models panel) + sec-scan integration (findings) | [ ] |
| 3 | Memory + Agents | memory timeline/search + agents status/delegation | [ ] |
| 4 | Portfolio kanban | Visual kanban board reading product `_index.md` status from vault | [ ] |

## Lifecycle

| Transition | Trigger | Date |
|------------|---------|------|
| → idea | Brainstorm session (IDP dashboard discussion) | 2026-02-21 |

## Backlog (when promoted)

> Stream G (Knowledge Base) task breakdown preserved from previous standalone roadmap. Source of truth for KB-001..007. Read-only web viewer for the Obsidian vault using Quartz, synced via Git cron (5 min). Defense-in-depth: Authelia (access) + Quartz filtering (content).

### Stream G — Knowledge Base (Quartz)

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

## Notes

- Intentionally the LAST product to build. L1-2 through L1-4 must have stable APIs first.
- Risk: scope creep. Every new service = new panel. Brutal MVP discipline required.
- Backstage was considered and rejected: too heavy to maintain for a single-developer platform.
- Lighter alternatives (Headlamp, Kubero) cover K8s but not the custom L1 services.
