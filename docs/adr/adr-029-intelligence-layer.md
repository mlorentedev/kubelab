---
id: adr-029-intelligence-layer
type: adr
status: active
created: "2026-03-28"
tags: [intelligence, llm, rag, hardware, architecture]
owner: manu
depends_on: [adr-026-idp-evolution]
---

# ADR-029: Intelligence Layer — Hardware Reallocation, Gateway Consolidation, and RAG Strategy

> **Status:** Accepted
> **Date:** 2026-03-28
> **Supersedes:** kubelab-gateway (absorbed), kubelab-memory (simplified)
> **Related:** ADR-026 (IDP Evolution), ADR-022 (OpenClaw), ADR-023 (Hub-and-Spoke GitOps)

## Context

Three unresolved gaps in the KubeLab platform:

1. **No automation layer** — content creation, task management, and daily planning are manual.
2. **Knowledge base decay** — vault documents drift out of date; agents and RAG built on stale data produce wrong outputs.
3. **No public-facing AI feature** — portfolio demonstrates infra skills but lacks a product-level AI differentiator.

Root cause: no intelligence layer between infrastructure and the human operator.

Four existing specs partially address this — `kubelab-gateway` (LLM routing, idea), `kubelab-memory` (knowledge graph, idea), `kubelab-agents` (OpenClaw, spec), ADR-026 (IDP evolution, active). They are fragmented and partially overlapping. This ADR consolidates them.

## Decisions

### 1. Hardware reallocation

Acemagic-2 has 12GB RAM — fits Mistral Nemo 12B Q4 (~7GB) comfortably. Beelink's 8GB is too tight for Ollama + OpenClaw + platform services simultaneously. OpenClaw consumes Ollama async — no need for same-node colocation.

| Node | Previous role | New role | Rationale |
|------|--------------|----------|-----------|
| Acemagic-2 (12GB) | K3s staging agent | Ollama bare metal (Mistral Nemo 12B Q4) | 12GB fits Nemo 12B + OS. Zero token cost for classification/tagging |
| Beelink (8GB) | Ollama + OpenClaw | Platform services (GH Runner + Gitea + OpenClaw + MinIO) | RAM freed for platform services |
| Acemagic-1 (12GB) | K3s staging all-in-one | K3s staging all-in-one (unchanged) | Staging becomes single-node — acceptable for solo operator |
| Jetson Nano (4GB) | Pollex | Pollex (unchanged) | Independent |

**Impact:** Staging becomes single-node (ace1). Validates manifests and ArgoCD sync, not HA.

### 2. Absorb kubelab-gateway into unified Go API

Standalone microservice for LLM routing adds deployment overhead without benefit at current scale (<5 consumers). Merge `/v1/llm/*` and `/v1/knowledge/*` into the existing kubelab Go API. One binary, one deployment.

**kubelab-gateway status: absorbed.**

Revisit when: >3 independent consumers require separate scaling.

### 3. Simplify kubelab-memory to pgvector RAG

Event-driven knowledge graph (Git webhooks, K8s watch, log parsers, dual storage) is overengineered for single-operator scale. Replace with pgvector RAG over vault documents. Operational events can be added as a pgvector collection later.

**kubelab-memory status: absorbed.**

Preserved: vector search (becomes RAG service in IDP Phase 2).
Dropped: event-driven ingestion (M1-M3). Hive MCP + claude-mem serves current needs.

### 4. PostgreSQL 16 + pgvector as unified data store

Single instance serves:
- LLM usage tracking (tokens, cost, latency per consumer/model/day)
- Vault embeddings (only `status: active` documents)
- DORA metrics persistence
- Intel data (when Stream P activates)

**Resolves:** Stream D "PostgreSQL decision pending."

### 5. LLM strategy

| Task type | Backend | Model | Why |
|-----------|---------|-------|-----|
| Triage, classification, tagging | Ollama local (ace2) | Mistral Nemo 12B Q4 | High volume, zero cost |
| Content drafts, long text | OpenRouter | DeepSeek V3 | Quality, affordable |
| Complex planning | OpenRouter | DeepSeek V3 / Claude | Multi-step reasoning |

Primary language: Spanish. Routing configured per task type in the API (not dynamic fallback).

### 6. "Chat with Manu" — portfolio deliverable

Public RAG widget on mlorente.dev. Full-stack AI demonstration (Astro + Go API + pgvector + K8s).

- Frontend: Astro component (HTMX or vanilla JS)
- Backend: `POST /v1/knowledge/chat` on kubelab API
- Data: pgvector embeddings of vault active documents (filtered for public-safe content)
- **Parallel workstream** — does NOT depend on ArgoCD or IDP catalog. Needs PostgreSQL + vault metadata only

### 7. Vault self-healing design principle

The vault must be trustworthy before RAG or agents produce value. Goal: **self-healing vault** maintained between human contributions and the OpenClaw agent.

**Required metadata on all active documents:**

| Field | Type | Purpose |
|-------|------|---------|
| `last_verified` | `YYYY-MM-DD` | When content was last confirmed accurate |
| `status` | `active \| draft \| stale \| archived` | Lifecycle state |
| `depends_on` | `[list]` | Documents to update when this one changes |
| `owner` | `manu \| agent` | Who maintains this document |

**Self-healing mechanisms:**
- **n8n cron:** Flag documents with `last_verified` > 30 days as `stale`
- **OpenClaw `vault-health` skill:** Report stale docs, broken links, orphans
- **Agent writes:** OpenClaw updates `last_verified` after reviewing, updates `status` on confirmation
- **pgvector filter:** Only `status: active` docs indexed — stale docs excluded from RAG automatically

### 8. Intel pipelines deferred to Stream P

RSS, YouTube, job boards, competitor watch — productivity features, not platform infrastructure. `/v1/intel/*` endpoints are premature abstraction.

**Decision:** Stream P (Portfolio Tools) as n8n standalone workflows. Consume LLM gateway, push to PostgreSQL, visualize via Grafana. No custom API endpoints until volume justifies.

## Integration with ADR-026

The intelligence layer integrates into ADR-026's 4-layer model, not as a parallel architecture:

| ADR-026 Layer | Intelligence Layer addition |
|---------------|---------------------------|
| Catalog | No change |
| Governance | No change |
| Agent | + LLM gateway (Ollama + OpenRouter) + RAG (pgvector) + vault-health skill |
| Portal | + "Chat with Manu" (mlorente.dev) + LLM usage dashboard (Grafana) |

IDP phases absorb the intelligence layer work:
- **Phase 0** gains: vault metadata, PostgreSQL + pgvector, ace2 Ollama provisioning
- **Phase 1** gains: LLM gateway endpoints, token tracking
- **Phase 2** gains: embedding pipeline, `/v1/knowledge/search`, "Chat with Manu", vault-health skill

### Canonical OpenClaw skills (consolidated from ADR-026 + this ADR)

| Skill | Source | Phase | Description |
|-------|--------|-------|-------------|
| `kubelab-catalog` | ADR-026 | IDP-1 | Service queries, dependency graphs |
| `kubelab-vault` | ADR-026 | IDP-1 | ADR/runbook search via Hive bridge |
| `kubelab-ops` | ADR-026 | IDP-1 | kubectl read-only, ArgoCD status |
| `kubelab-ssot` | ADR-026 | IDP-1 | Structured common.yaml queries |
| `llm-router` | ADR-027 | IDP-1 | Route prompts to local/cloud model |
| `vault-health` | ADR-027 | IDP-2 | Stale doc detection, freshness reports |
| `content-draft` | ADR-027 | Stream P | Newsletter/blog drafts (deferred) |
| `intel-briefing` | ADR-027 | Stream P | Daily morning briefing (deferred) |
| `kubelab-deploy` | ADR-026 | IDP-4 | YAML generation + PR (human-in-the-loop) |

## Consequences

### Positive

- Consolidates 4 fragmented specs into one coherent plan
- Hardware optimized for actual workloads (12GB for LLM, 8GB for services)
- PostgreSQL decision resolved (was "pending" since Stream D creation)
- "Chat with Manu" is a tangible, demonstrable portfolio piece
- Vault self-healing reduces manual maintenance burden
- Vault quality improvements benefit RAG, IDP catalog, and agent trustworthiness simultaneously

### Negative

- Staging loses a node (ace2) — becomes single-node
- kubelab-memory's operational event model dropped (may need later)
- Monolith API limits independent scaling (acceptable at current scale)

### Risks

- Vault metadata cleanup is ~200+ documents — large manual effort, mitigated by scripting
- Mistral Nemo 12B quality for Spanish tasks unknown — evaluate before committing
- PostgreSQL on single-node K3s staging has no HA — acceptable for non-critical data, mitigated by pg_dump backups

## External Reference Implementations

### agent-memory.dev (Apache-2.0)

**URL:** https://www.agent-memory.dev/

Open-source persistent memory runtime for coding agents. Single-process Node.js, no external DBs. Tracked as an architectural reference for IDP Phase 2 RAG and the `vault-health` skill — not as a runtime dependency.

**Overlap with this ADR (Phase 2):**

| Capability | This ADR | agent-memory.dev | Cherry-pick? |
|---|---|---|---|
| Hybrid retrieval | pgvector + BM25 (planned) | BM25 + vector + KG, on-device rerank, 95.2% R@5 LongMemEval-S | Yes — architecture pattern |
| Knowledge graph | Manual `depends_on` per doc | Auto entity + temporal relation extraction | Yes — feed `depends_on` suggestions (SH-005) |
| Consolidation | Manual `/crystallize` skill | Hourly auto-consolidation with dedup | Adapt — keep human-in-the-loop |
| MCP surface | Hive MCP (vault) + claude-mem (sessions) | 51 MCP tools + 121 HTTP endpoints | No — already covered |
| Storage | pgvector + Postgres | JSON on disk, no DBs | No — doesn't fit IDP scale plan |

**Why reference only, not adopt:**

- Auto-captures sessions via 12 hooks → conflicts with claude-mem capture (double ingest, duplicate token cost).
- Mirrors to a "sandboxed vault" → would pollute the curated vault (32-field `types.json`, `_ssot.md`, naming discipline). Two markdown sinks violates SSOT.
- Hourly auto-consolidation bypasses human curation — incompatible with the Competence Retention protocol.

**Where to mine value:**

1. Read its retrieval engine (BM25 + vector + KG with rerank) before designing `/v1/knowledge/search` in IDP Phase 2.
2. Evaluate its KG entity extractor as a sandbox accelerator for SH-005 (`depends_on` auto-expansion) — see `10_projects/knowledge/11-tasks.md`.
3. OTEL tracing patterns for agent observability when the `vault-health` skill ships.

**Status:** Reference only. Re-evaluate if Phase 2 retrieval needs to be re-implemented from scratch.

## Implementation

Tasks in `11-tasks.md` Stream IDP (phases updated to absorb intelligence layer).
Hardware: ANSIBLE-013 (Beelink) + IDP-024 (ace2 Ollama).
Vault health: IDP-020..022 (P0 priority, no gates — start immediately).
