---
id: adr-043-unified-knowledge-memory-plane
type: adr
status: accepted
created: "2026-06-11"
owner: manu
tags: [architecture, knowledge, memory, rag, pgvector, mcp, vault, open-webui, hermes, agents]
depends_on: [adr-028-operational-topology, adr-029-intelligence-layer, adr-042-reference-architecture]
---

# ADR-043: Unified Knowledge/Memory Plane (vault SSOT across all agent surfaces)

> **Status:** Accepted
> **Date:** 2026-06-11
> **Related:** ADR-029 (intelligence layer: pgvector RAG), ADR-028 (always-on vs on-demand), ADR-042 (reference architecture; Open WebUI as operator console)
> **Research:** vault `10_projects/kubelab/40-research/research-memory-ssot.md` (2026-06-11) — option space, trade-off matrix, sources. Ticket: AI-006 (#595).

## Context

Every agent surface in the ecosystem — coding agents (Claude Code/OpenCode/pi), the planned Open WebUI operator console (AI-003), the remote Hermes ops agent, and a future public chat widget — should share the SAME source of truth for knowledge and memory. Today each surface has a private slice: the Obsidian vault (git + hive MCP) for curated knowledge, claude-mem SQLite per machine for session observations, Hermes `/persist` on the NaN server, and Open WebUI would add its own RAG store by default.

"Same memory" conflates three data planes that need separate treatment:

- **(i) Canonical knowledge** — curated vault docs (git repo, English, frontmatter law).
- **(ii) Derived searchable index** — embeddings/search over (i).
- **(iii) Session/episodic memory** — conversation traces, handoffs, observations.

Hard constraints: the vault must stay readable when ALL infra is down (it is the recovery manual); staging is on-demand (ADR-028) so nothing always-on may depend on it; a public widget cannot speak MCP (needs REST); writes must stay curated (English-canonical doctrine) — an extractor LLM mutating content before storage is unacceptable.

## Reference audit (Regla del 3)

Verified mid-2026 (full citations in the research doc):

| Dimension | R1 · Open WebUI | R2 · Hermes Agent | R3 · Vault-RAG references |
|---|---|---|---|
| MCP client | Native since v0.6.31, **Streamable HTTP only**; Bearer / OAuth 2.1 static (Authelia-compatible) | HTTP MCP via `url`+`headers`; bearer, OAuth 2.1, mTLS | IBM ContextForge gateway: one MCP endpoint, many clients, per-client tool ACLs |
| External knowledge | Knowledge collections + `oikb` sync; `VECTOR_DB=pgvector` pluggable; REST ingest is async/fiddly | Reads vault via git (constitution model); `/persist` for state | Cazanove (vault→Meilisearch→REST→LibreChat), briankeefe (vault→FAISS→FastAPI→Open WebUI), Khoj (productized) |
| Memory services | Built-in per-user memory (beta, not shareable) | Feature request to expose memory via MCP (#10835) | mem0/OpenMemory: corruption + blocking bugs; Zep CE deprecated (Graphiti+graph DB); Letta agent-centric. **None solves cross-agent (iii) today**; Basic Memory validates "markdown+index = memory" |

## Decision

**Layered hybrid: A (git-as-bus) + C (RAG read layer) + D-lite (vault as episodic store). B (network-served hive MCP) deferred as a later increment.**

1. **Plane (i) — git stays the bus.** The vault remains canonical, synced via obsidian-git/hive exactly as today. Hermes keeps consuming it via git (offline-tolerant). No change.
2. **Plane (ii) — one derived index serves every consumer.** Embedding pipeline: vault git → chunk → embed → **pgvector on prod VPS K3s** (always-on, ADR-028) → **`POST /v1/knowledge/search`** in the Go API. Consumers: Open WebUI (OpenAPI tool), Hermes (HTTP tool), coding agents (thin MCP tool), future public widget (same REST behind separate ingress + rate limits). This implements ADR-029's RAG direction; the index is derived and rebuildable — no backup burden.
3. **Plane (iii) — D-lite, no dedicated memory service.** Handoffs, lessons, and claude-mem distillates keep funneling INTO the vault (existing practice); the pipeline indexes them, making episodic memory searchable through the same plane-(ii) API. An Open WebUI conversation-capture hook (Filter Function → hive) is future work inside AI-003 scope or follow-up.
4. **B deferred.** Serving hive over Streamable-HTTP MCP (bearer over Headscale, hosted always-on on the VPS — never on-demand staging) is a clean later increment for write-from-chat (`capture_lesson` from Open WebUI). Trigger to activate: a real write-from-chat need, or ≥2 consumers duplicating write logic.

### Resolved design questions

| Question | Decision |
|---|---|
| Scope of "same memory" | (i)+(ii) unified now; (iii) via D-lite funneling. No cross-agent conversational recall service. |
| Open WebUI placement | Stays on staging per ADR-042/AI-003. Explicit revisit trigger: if it becomes the primary operator console, move to prod VPS (RAM budget check on CAX21 first). Decided during AI-003 validation. |
| Freshness SLO (plane ii) | Phase 1: pipeline cron ≤15 min (on top of obsidian-git ~10-min floor) — acceptable. Phase 2: Gitea push webhook → pipeline, only when staleness actually hurts. |
| Auth for remote consumers | Bearer token over Headscale (tag ACLs, ADR-041) for internal consumers. Public widget bypasses VPN: separate IngressRoute + rate limiting + doc-level allowlist in the API. No OAuth 2.1 ceremony until B lands. |
| Index multiplicity | Open WebUI native Knowledge/RAG **disabled by policy** — consumption is tool-only against `/v1/knowledge/search`. One index, one ranking, no drift. |
| Hermes write authority | Unchanged: read-only on the vault + `/persist` + sandbox research promotion per `pattern-research-placement`. Multi-writer git is not opened. |
| Embedding exclusions | Secrets hygiene: SOPS-adjacent paths, `80_agents/` private state, and any `status: archived` docs are excluded from the pipeline. Allowlist-by-directory, reviewed in IDP-027. |

### Implementation sequencing (existing tickets — no new ones)

IDP-023 (#299, Postgres16+pgvector on prod) → IDP-027 (#395, embedding pipeline) → IDP-028 (#396, search API) → consumer wiring (AI-003 Open WebUI tool; Hermes tool; coding-agent MCP tool) → IDP-025/026 (#375/#379, LLM gateway/dashboard) proceed independently. AI-003 is NOT blocked by any of this.

## Rejected

- **Dedicated memory service (mem0/OpenMemory, Zep/Graphiti, Letta)** — worst maturity (memory-corrupting extractor, CE deprecation precedent, agent-centric model), new always-on stateful infra with real backups, and a second knowledge store that drifts from the vault. Re-evaluate only if a true cross-agent conversational-recall requirement emerges that D-lite cannot satisfy.
- **B as primary (central hive MCP for everything)** — single point of failure for every agent's knowledge tools (vs git's local-copy degradation), no public-widget path, and search stays lexical.
- **Open WebUI native KB as the shared index** — per-product index invisible to other consumers; ingestion API is async/fragile; would duplicate the pgvector index.
- **Vault-root global research/index sections** — hive addresses `10_projects/<slug>` + `00_meta` only (see `pattern-research-placement`).

## Consequences

- One semantic search surface for everything the vault knows, including handoffs/lessons — at the cost of operating the pipeline (cron, chunking quality, exclusion list).
- The vault's offline guarantee is preserved: losing VPS/VPN degrades search, never canonical knowledge.
- Open WebUI arrives (AI-003) already pointed at the shared index — no migration later.
- kubelab-memory (L1 product slot) gets its concrete shape: pipeline + search API, not a memory service.
