---
id: adr-026-idp-evolution
type: adr
status: active
created: "2026-03-27"
tags: [idp, architecture, platform-engineering, portfolio]
owner: manu
---

# ADR-026: KubeLab IDP Evolution — Custom Catalog, Governance, and Agent-Driven Platform

> **Status:** Accepted
> **Date:** 2026-03-27
> **Supersedes:** None
> **Related:** ADR-022 (OpenClaw agent deployment), ADR-023 (Hub-and-Spoke GitOps), ADR-009 (Prometheus metrics), ADR-007 (task delegation)

## Context

KubeLab has grown from a Docker Compose homelab into a hybrid-cloud platform running 31+ services across 6 nodes with K3s, Kustomize, ArgoCD (in progress), SOPS secrets, Authelia SSO, and a toolkit CLI for orchestration. The infrastructure works, but it operates as a **toolkit** — imperative scripts executing against scattered state.

An Internal Developer Platform (IDP) is fundamentally different:

- **Data model relacional**: a catalog of entities (services, resources, nodes) with typed relationships — not commands
- **Reconciliation loop**: desired state declared, controllers converge reality (Argo CD, Kyverno) — not fire-and-forget
- **Policy engine**: admission control evaluates every change against organizational rules — not post-hoc validation
- **Event-driven reactions**: service registration triggers dashboard creation, monitoring setup, DNS — not scripted sequences

The CLI (`toolkit`) remains the executor. The IDP adds the abstraction and state layers on top.

### Strategic context

KubeLab IDP serves three purposes simultaneously:

1. **Portfolio asset** — demonstrates platform engineering skills for senior PE roles (target: €60-75K in Spain). Building a custom IDP proves architectural judgment, not just tool installation.
2. **Content engine** — each phase produces YouTube episodes + newsletter material. The journey "from toolkit to IDP" is a complete narrative arc.
3. **Freelance foundation** — the platform becomes the base for managed IDP-as-a-service consulting. Client isolation, governance, and promotion pipelines are directly reusable.

## Decision

### Why NOT Backstage

Backstage requires PostgreSQL, Node.js runtime, and ongoing plugin maintenance. The operational overhead is unjustifiable for a single operator with 15 services. A custom catalog YAML + toolkit CLI + OpenClaw agent skills delivers ~90% of the value at ~10% of the complexity.

**Revisit when:** multi-team usage or client self-service portal justifies the overhead.

### Why NOT Crossplane (yet)

Crossplane adds a full control plane (provider pods, CRDs, compositions) consuming RAM and CPU. The hub t4g.micro already operates at RAM limits with Argo CD alone. No self-service users exist yet.

**Revisit when:** clients request infrastructure resources via PR, or hub hardware allows it.

### What we build instead

Custom catalog YAML + toolkit CLI extensions + OpenClaw agent skills (ref ADR-022) + n8n workflow orchestration + Homepage/Astro portal. This combination is itself a portfolio differentiator: demonstrates the judgment to choose the right tool at the right scale.

### Architecture: four layers

```
┌──────────────────────────────────────────────────┐
│  PORTAL LAYER                                    │
│  Homepage (Phase 0) → Astro custom (Phase 3)     │
│  Grafana embeds, DORA metrics, catalog view       │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────┐
│  AGENT LAYER                                     │
│  OpenClaw (ADR-022) + kubelab skills             │
│  Telegram/Slack → catalog, vault, ops, health     │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────┐
│  GOVERNANCE LAYER                                │
│  Kyverno policies + ApplicationSet + promotion    │
│  Labels, limits, registries, network policies     │
└────────────────────┬─────────────────────────────┘
                     │
┌────────────────────┴─────────────────────────────┐
│  CATALOG LAYER (foundation)                      │
│  catalog/*.yaml generated from common.yaml       │
│  Machine-readable service relationships           │
│  tk catalog {list,show,deps,health,sync}          │
└──────────────────────────────────────────────────┘
```

### Catalog schema

Generated from `infra/config/values/common.yaml` — projection, not duplication. The toolkit command `tk catalog sync` regenerates from SSOT and detects drift.

```yaml
apiVersion: kubelab.live/v1
kind: Component
metadata:
  name: grafana
  labels:
    app.kubernetes.io/part-of: kubelab
    kubelab.live/tier: observability
spec:
  type: service
  owner: manu
  lifecycle: production
  source: helm
  environments: [staging, prod]
  dependsOn:
    - service:loki
    - service:authelia
    - service:redis
  endpoints:
    health: /api/health
    dashboard: https://grafana.kubelab.live
  observability:
    logs: loki
    dashboard: kubelab-logs-overview
```

### Portal strategy

Two-phase approach:

| Phase | Tool | Role |
|-------|------|------|
| **0 (now)** | Homepage (gethomepage.dev) | Service directory + Grafana embeds + ArgoCD widget + DORA v0. YAML config, zero custom code. |
| **3 (after catalog populated)** | Astro custom portal (DASH-002) | Catalog view with dependency graph, real-time status, Grafana panels per service, vault runbook links, DORA metrics v1. |

Homepage is a startpage — adequate for single-operator use. The Astro portal is the portfolio/client-facing asset built when the catalog has real data to display.

### DORA metrics

Explicit requirement for portfolio credibility. A Platform Engineer candidate without deployment metrics lacks proof.

| Metric | Source | Phase |
|--------|--------|-------|
| Deployment frequency | GitHub Actions API (deploy timestamps) | v0 (Phase 0) |
| Lead time for changes | Git log analysis (commit → deploy via ArgoCD) | v0 (Phase 0) |
| Mean time to recovery | Uptime Kuma incident duration | v1 (Phase 2) |
| Change failure rate | ArgoCD sync failures / total syncs | v1 (Phase 2) |

v0 = Grafana dashboard with manual data pipeline. v1 = automated instrumentation across full pipeline.

### Agent integration

OpenClaw deployment architecture defined in ADR-022. This ADR adds kubelab-specific skills:

| Skill | Phase | Access | Description |
|-------|-------|--------|-------------|
| `kubelab-catalog` | 1 | Read catalog/*.yaml | Service queries, dependency graphs, state |
| `kubelab-vault` | 1 | Via Hive MCP bridge | ADR/runbook/troubleshooting search (reuses existing Hive, not new index) |
| `kubelab-ops` | 1 | kubectl (read-only) | Health checks, ArgoCD sync status, pod listing |
| `kubelab-ssot` | 1 | Read common.yaml | Structured queries ("all services with enable_auth: true") |
| `kubelab-deploy` | 4 | Git write (PR) | Generate YAML from catalog schema, open PR. Human-in-the-loop. |

LLM routing per ADR-022: qwen3:8b on Beelink (local, 8GB RAM constraint — 14b does not fit in Q4), Claude API via OpenRouter for complex queries.

### n8n as execution layer

n8n (already deployed in K3s) provides multi-step workflow execution. OpenClaw triggers via webhooks, n8n executes, OpenClaw reports results.

Target workflows:
- Health check completo (all catalog endpoints → Telegram report)
- Backup on-demand (webhook → Ansible playbook → report)
- Daily digest (ArgoCD sync + health + resource usage → Telegram)

**GitOps requirement:** n8n stores workflows in its internal DB, which violates SSOT. Mitigation: `n8n export` to Git on every workflow save (APP-CONFIG-003 in 11-tasks.md). Workflows versioned in `infra/config/seeds/n8n-workflows/`.

## Evolution plan — ordered by dependency

### Phase 0: Foundation

> **Pre-requisite:** ADR-023 Phase 3 (ArgoCD) completed.

- **IDP-001**: Update README to reflect current state (portfolio landing page)
- **IDP-002**: Catalog YAML generator (`tk catalog sync` — common.yaml → catalog/*.yaml)
- **IDP-003**: DASH-001 evolution — ArgoCD widget + Grafana embeds in Homepage
- **IDP-004**: DORA metrics v0 — Grafana dashboard (GH Actions + ArgoCD events)

### Phase 1: Catalog + Agents

> **Pre-requisite:** Phase 0 + Beelink provisioned (ANSIBLE-013).

- **IDP-005**: `tk catalog {list,show,deps,health,sync}` CLI subcommands
- **IDP-006**: Hive MCP → OpenClaw bridge (expose vault as skill, not new index)
- **IDP-007**: OpenClaw gateway on Beelink (ref ADR-022 Phase 0)
- **IDP-008**: OpenClaw kubelab skills (read-only): catalog, vault, ops, ssot
- **IDP-009**: n8n workflows + Git export strategy (health, backup, digest)

### Phase 2: Governance + Templates

> **Pre-requisite:** Phase 1 + ADR-023 Phase 4 (security baseline).

- **IDP-010**: Kyverno policies (require-labels, require-limits, restrict-registries, default-network-policy)
- **IDP-011**: ApplicationSet (replace dual Application YAMLs)
- **IDP-012**: `tk new service --type backend` (golden path generator)
- **IDP-013**: Promotion pipeline staging → prod (n8n + PR gate)
- **IDP-014**: DORA metrics v1 (full pipeline instrumentation)

### Phase 3: Portal + Multi-tenancy

> **Pre-requisite:** Phase 2 + catalog populated with real data.
> **Business offering spec:** `20-business/offers/02-idp-service.md`

- **IDP-015**: Astro IDP portal (DASH-002) — catalog view, dependency graph, status, runbook links
- **IDP-016**: Client isolation primitives (namespace, AppProject, SOPS key, ResourceQuota, NetworkPolicy)
- **IDP-017**: Client-facing OpenClaw (scoped per AppProject)

### Phase 4: Autonomous agents

> **Pre-requisite:** Phase 3 + proven stability.

- **IDP-018**: OpenClaw deploy skill (generate YAML, open PR, human-in-the-loop via merge)
- **IDP-019**: Claude API for complex analysis (log anomaly detection, capacity planning)

### Observability (Prometheus, Alertmanager, SLOs)

**Not duplicated here.** Defined in ADR-023 Phase 6. Executed in parallel when ADR-023 reaches that phase. DORA metrics (above) are IDP-specific and complementary.

## Consequences

### Positive

- Custom IDP is a portfolio differentiator vs "I installed Backstage"
- Each phase is independently valuable and demoable (content + portfolio)
- Catalog schema is Backstage-compatible if migration ever needed
- Agent skills (OpenClaw) provide a conversational interface unique in the market
- DORA metrics give quantitative proof of platform maturity

### Negative

- Custom catalog lacks the Backstage plugin ecosystem
- Maintenance burden: catalog sync, Kyverno policies, portal — all custom code
- No community support for the custom catalog format

### Risks

- Scope creep: IDP evolution is unbounded. Phases gate this, but discipline is required.
- Phase 3 (multi-tenancy) depends on having actual clients. Without clients, it's speculative engineering.
- OpenClaw + Ollama on 8GB Beelink may be tight — monitor RAM usage early.

## Implementation

Detailed specs per component created just-in-time in `30-architecture/idp-*-spec.md` when starting each phase. This ADR is the strategic decision, not the implementation guide.

Task tracking: `11-tasks.md` Stream IDP (IDP-001..019).
Business offering: `20-business/offers/02-idp-service.md`.
