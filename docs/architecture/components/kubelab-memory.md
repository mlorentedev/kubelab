---
id: kubelab-memory
type: architecture
status: absorbed
absorbed_by: adr-029-intelligence-layer
absorbed_on: "2026-03-28"
created: "2026-05-09"
owner: manu
---

# kubelab-memory (component spec)

> **Status:** `absorbed` — replaced by pgvector RAG over vault documents (PostgreSQL 16 + pgvector) per [ADR-029](../../adr/adr-029-intelligence-layer.md) (2026-03-28).
> **Do not implement.** Backlog kept for historical context only.
> **Parent:** kubelab
> **Layer:** L1-platform

## Problem (historical)

Operational context is lost between sessions. Agents don't know what happened in previous deploys, why something failed, or what decisions were made. Today this is managed manually via Obsidian vault + claude-mem MEMORY.md. Works for one human, doesn't scale to agents or automation.

## Solution (historical)

Event-driven knowledge graph that automatically ingests platform events (commits, PRs, deploys, rollbacks, pod crashes, alerts) and builds a searchable operational memory. Exposed via MCP server (for agents) and CLI (for humans). Think: Rowboat but specialized for platform operations instead of generic work.

## How it was absorbed (ADR-029)

The event-driven knowledge graph was abandoned in favor of **pgvector RAG over vault documents** (PostgreSQL 16 + pgvector). Reasons:

- **Vector search (M4) preserved** as the RAG service in IDP Phase 2.
- **Event-driven ingestion (M1-M3) dropped** — Hive MCP + claude-mem already serves the current single-operator needs without building a separate event store.
- Avoids duplicating infrastructure (event store + graph DB + vector DB) when a single pgvector install covers the actually-needed search use case.

## Tech Stack (historical)

| Component | Technology |
|-----------|-----------|
| Language | Go or Python |
| API | MCP server + REST |
| CLI | `kubelab memory search "why did deploy X fail"` |
| Storage | SQLite or PostgreSQL (text/graph) + Qdrant/ChromaDB (vectors) |
| Ingestion | Webhooks (Git), K8s watch API, log parsers |
| Embeddings | Ollama local (always, for corporate data safety) |
| Search | Text search (M1-M3) + vector/semantic search (M4) |

## Dependencies (historical)

- kubelab L0 (K3s, Git webhooks)
- Stream D (Observability) for full ingestion — but MVP works with Git only
- Consumers: [kubelab-agents](kubelab-agents.md), [kubelab-console](kubelab-console.md)

## Decisions (historical)

| Decision | Choice | Reason | Date |
|----------|--------|--------|------|
| Interface | MCP + CLI | MCP for agent consumption, CLI for humans. Same API underneath | 2026-02-21 |
| MVP scope | Git-only (no observability dependency) | Unblocks parallel development, already valuable with Git data | 2026-02-21 |
| **Replacement** | **pgvector RAG over vault documents** | **Avoids duplicate event store; Hive + claude-mem covers current needs** | **2026-03-28 (ADR-029)** |

## Milestones (historical, never executed)

| # | Milestone | Done criteria | Status |
|---|-----------|---------------|--------|
| 1 | Git event store | Webhook → event store + MCP server with basic text search | [-] dropped |
| 2 | K8s event watcher | Deploy, rollback, pod crash events ingested | [-] dropped |
| 3 | Observability integration + CLI | Logs/metrics/alerts ingested, `toolkit memory` CLI works | [-] dropped |
| 4 | Vector search | Vault Markdown + Git diffs indexed with local embeddings (Ollama). Semantic search via MCP. Dual scope: personal (10_projects/) + work (50_work/) | [→] preserved as pgvector RAG (IDP Phase 2) |

## Lifecycle

| Transition | Trigger | Date |
|------------|---------|------|
| → idea | Brainstorm session (Rowboat comparison) | 2026-02-21 |
| → spec | Stream F5 fully defined | 2026-02-22 |
| → absorbed | ADR-029 (Intelligence Layer) | 2026-03-28 |

## Historical Backlog (do not implement)

> Originally Stream F5 (MEM-001..005). Functionality replaced by pgvector RAG. Kept for archaeology only.

### Agent Persistent Memory (F5) — historical

- [-] **MEM-001**: Design memory architecture (MEMORY.md + QMD hybrid)
  - **Decision**: Same pattern as Claude Code — proven in daily use
  - MEMORY.md: flat file loaded at session start (conventions, decisions, preferences, ~200 lines)
  - QMD: structured observation database (searchable by date/type/project/keyword)
  - Evaluate QMD options for self-hosted: sqlite-based, file-based JSON, or lightweight DB
  - Must run on RPi 4 (arm64, 8GB) — no heavy dependencies
- [-] **MEM-002**: Implement chosen memory system
  - Agent reads memory on startup / before each task
  - Agent writes learnings after task completion
  - Memory includes: project conventions, past decisions, error patterns, user preferences
  - Timestamped entries for freshness tracking
- [-] **MEM-003**: Define memory lifecycle
  - What to remember: confirmed patterns, architectural decisions, user preferences, bug fixes
  - What to forget: session-specific context, speculative conclusions
  - Pruning strategy: stale entries after N days without reference
  - Memory budget: max file size or entry count to prevent bloat
- [-] **MEM-004**: Integration with agent workflows
  - OpenClaw: pre-task memory load, post-task memory write
  - PicoClaw: persistent context across chat sessions
  - n8n: pass relevant memory context in task execution payload
- [-] **MEM-005**: Test memory persistence
  - Agent completes task A → learns pattern → completes task B using that knowledge
  - Agent restart → memory survives
  - Verify: no hallucinated memories, no stale data causing bad decisions

## Notes (historical)

- Absorbed kubelab `todo.md` Stream F5 (Agent Persistent Memory, MEM-001..005)
- Inspired by Rowboat (rowboatlabs, YC-backed) but specialized for platform ops
- Current manual equivalent: Obsidian vault + claude-mem MCP + MEMORY.md
- Key risk that drove the absorption decision: knowledge graph quality is hard — must produce useful queries, not a data dump. pgvector + RAG gives a simpler path to "useful query" without standing up an event store.
