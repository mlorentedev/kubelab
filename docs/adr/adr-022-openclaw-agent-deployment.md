---
id: adr-022-openclaw-agent-deployment
type: adr
status: superseded
superseded_by: adr-002-orchestrator-architecture
created: "2026-03-15"
owner: manu
---

# ADR-022: OpenClaw Agent Deployment — Beelink, Inbox Pattern, Hybrid LLM Routing

## Status

Accepted (2026-03-15). Refines ADR-007 (execution model, hardware, LLM strategy). ADR-007 remains valid for the full task delegation vision (Vikunja + n8n + human-in-the-loop).

## Context

ADR-007 defined the agent orchestration architecture (Vikunja + n8n + OpenClaw) with OpenClaw on RPi 4. Since then:

1. **RPi 4 is overloaded** — it serves as NAT gateway, dnsmasq DHCP, Pi-hole, CoreDNS. Adding agent workloads is risky.
2. **Beelink already runs Ollama** (Qwen2.5:7b) — colocating OpenClaw there eliminates network latency for local inference.
3. **OpenClaw matured** — 302k+ GitHub stars, native Telegram/Slack support, Docker sandboxing, MCP client support.
4. **Hive MCP server (v1.11.5)** already provides full vault CRUD — no need to build custom vault integration.
5. **OpenRouter** provides model routing as a service — building kubelab-gateway for the MVP is unnecessary complexity.

The goal: get a working personal AI assistant (the "newsletter guy" pattern) before tackling full task delegation.

## Decision

### Hardware: Beelink over RPi 4

| Criterion | RPi 4 | Beelink |
|-----------|-------|---------|
| Available RAM | ~3GB (gateway duties) | ~8GB (Ollama-only) |
| Architecture | ARM64 (Docker compat issues) | x86_64 (full compat) |
| Ollama colocated | No (network hop) | Yes (localhost) |
| Current load | High (gateway + DNS + DHCP) | Low (Ollama idle) |

OpenClaw runs on **Beelink (kubelab-bee)** in Docker with resource limits.

### LLM Routing: Ollama local + OpenRouter cloud

No kubelab-gateway in MVP. Direct routing:

| Task type | Model | Provider | Cost |
|-----------|-------|----------|------|
| Classification, tagging | Qwen2.5:1.5b | Ollama local (on-demand) | $0 |
| Summarization, content | Qwen2.5:7b | Ollama local (on-demand) | $0 |
| Complex reasoning, connections | Claude Opus | OpenRouter | ~$15/M tokens |
| Scheduled cronjobs | Gemini Lite | OpenRouter | ~$0.075/M tokens |

Ollama loads models on-demand (5-min idle timeout). Budget cap: **$5-10/week** on OpenRouter via a **dedicated API key** with spending limit (not the personal key).

### Vault Access: Hive MCP with inbox isolation

OpenClaw connects to Hive MCP server running locally on Beelink with a **cloned copy of the vault** (git sync).

**Write isolation — the inbox pattern:**

| Vault zone | OpenClaw permission |
|------------|-------------------|
| `00_meta/` | READ-ONLY (learns patterns, templates, taxonomy) |
| `10_projects/` | READ-ONLY (understands project context) |
| `20_certifications/` | READ-ONLY |
| `30_career/` | READ-ONLY |
| `40_resources/` | READ-ONLY |
| `50_work/` | READ-ONLY |
| `80_inbox/` | **READ-WRITE** (agent's exclusive write zone) |
| `90_archive/` | READ-ONLY |

Enforced at Hive config level (path prefix restriction on write operations). The agent follows vault frontmatter standards (id, type, status, tags) by reading `00_meta/` patterns.

**Human review workflow:** User opens `80_inbox/` in Obsidian → reviews agent output → promotes to correct vault zone or discards. Like a PR review for knowledge.

**Git sync:**
- Pull: cron every 5-10 min on Beelink (or post-push hook from workstation)
- Push: immediate after each write to `80_inbox/` (Hive auto-commits)
- Conflicts: impossible if only the agent writes to `80_inbox/` and user never edits there directly (only moves files out)

### Docker Resource Limits

```yaml
services:
  openclaw:
    mem_limit: 2g
    cpus: 2
    # Ollama retains ~5-6GB for model loading
```

### Input Channels

Primary: **Telegram** (OpenClaw native support). Forward articles, ideas, notes → agent processes and writes to `80_inbox/`.

Future (Phase 1): n8n as multi-source ingestion — email forwarding, RSS feeds, GitHub webhooks.

### Phased Rollout

| Phase | Scope | Dependencies |
|-------|-------|-------------|
| **0 — MVP** | OpenClaw + Telegram + Ollama + OpenRouter + Hive → `80_inbox/` | Beelink Docker, vault clone, OpenRouter key |
| **1 — Workflows** | n8n as scheduler. Daily digest, RSS ingestion, reminders. Gemini Lite for cronjobs. | n8n (already in staging) |
| **2 — Task delegation** | Vikunja + full ADR-007 flow. Human-in-the-loop, L1-L3 autonomy levels. | Vikunja deploy, Slack integration |

## Explicit Limits (MVP)

| Limit | Reason |
|-------|--------|
| Agent writes only to `80_inbox/` | Prevent vault corruption, human curation |
| No auto-merge of PRs | Human always decides (inherited from ADR-007) |
| No production access | Agents only in dev/staging (inherited from ADR-007) |
| No SOPS/secrets access | Security (inherited from ADR-007) |
| Dedicated OpenRouter API key | Budget isolation, spending cap enforcement |
| Docker mem_limit 2GB | Protect Ollama from resource starvation |

## Consequences

1. **kubelab-gateway deferred** — OpenRouter handles routing in MVP. Gateway becomes relevant only if local routing rules get complex or cost savings from local-first justify the build.
2. **kubelab-memory deferred** — Hive + vault clone covers agent memory needs for MVP. The event-driven knowledge graph is a Phase 2+ concern.
3. **RPi 4 stays focused** — gateway duties only, no agent workloads.
4. **Beelink becomes the AI node** — Ollama + OpenClaw colocated. Resource monitoring recommended (Uptime Kuma + Grafana).
5. **`80_inbox/` created** — new vault zone exclusively for agent output, with documented conventions.
6. **ADR-007 not superseded** — it remains the target architecture for full task delegation. This ADR defines the pragmatic MVP path to get there incrementally.

## Scope Expansion (2026-03-25)

### Content Generation Pipeline

- Agents write content drafts (YouTube scripts, newsletter, blog posts) to Gitea repo via PR
- Gitea (gitea.kubelab.live) serves as content hub: `mlorentedev/content` repo with youtube/, newsletter/, blog/ directories
- Flow: Vikunja task (content:draft) → n8n trigger → OpenClaw delegates → agent reads vault context → generates draft → creates PR in Gitea → human reviews → merge → n8n triggers publish
- Human always merges. Agents never publish directly.

### LLM Routing (3-tier)

| Tier | Engine | Use Case | Cost |
|------|--------|----------|------|
| Local | Ollama (Qwen2.5 1.5b/7b) | Tagging, classification, short summaries, triage | $0 |
| Cloud mid | OpenRouter (Sonnet/Gemini) | PR review, linting, scheduled tasks | ~$10-15/mo |
| Cloud heavy | Claude Code subscription + OpenRouter Opus | Content generation, architectural reasoning, complex connections | Existing subscription + ~$10-15/mo overflow |

### Agent Roster (Spanish Classic Writers)

| Agent | Phase | Role | Input → Output | LLM Tier |
|-------|-------|------|-----------------|----------|
| **Cervantes** (orchestrator) | 2 | Task routing, delegation, status tracking | Vikunja/Telegram → task assignments | Cloud mid |
| **Quevedo** (knowledge capture) | 0 | Inbox processing, tagging, vault writing | Telegram → 80_inbox/ with frontmatter | Local + Cloud heavy |
| **Lorca** (content writer) | 1 | YouTube scripts, newsletter drafts, blog posts | Vault + yt-metrics → Gitea PR | Cloud heavy (Claude Code) |
| **Machado** (reviewer) | 1 | Code/config review, YAML lint, K8s validation | GitHub/Gitea webhooks → PR comments | Cloud mid |
| **Bécquer** (editor) | 2 | Newsletter polish, blog refinement | Vault lessons → refined drafts in Gitea | Cloud heavy |
| **Unamuno** (monitor) | 1 | Infra monitoring, alert triage | Uptime Kuma → classified alerts | Local + Cloud mid |

### Automation Boundary (Human-as-Brand)

- **Automated (backoffice):** Tagging, classification, draft generation, PR review, alert triage, SEO metadata, newsletter templates, content calendar management
- **Human only (brand vehicle):** Voice recording, paper diagrams, video editing, final review/approval, merge decision, community interaction, strategic decisions
- Principle: Automate everything that doesn't carry the personal brand signature. The overhead whiteboard, the voice, the diagnostic judgment — that stays human.

### Gitea Integration

- Agent access via dedicated bot account with scoped OIDC token
- Repo allowlist per agent (Lorca/Bécquer: content repo only, Machado: kubelab repos only)
- Webhooks: Gitea → n8n for PR events, merge triggers
- Content repo structure: youtube/{season}/{episode}-draft.md, newsletter/{year}-W{week}.md, blog/posts/{slug}.md

### Security Additions

- Claude Code usage: via user's existing subscription, not separate API key
- Gitea tokens: OIDC-scoped, 90-day rotation, repo-restricted
- Content never auto-publishes: human merge gate on all content PRs

## Related

- [adr-007-vikunja-n8n-openclaw-task-delegation](adr-007-vikunja-n8n-openclaw-task-delegation.md) — Full task delegation architecture (target)
- [adr-003-hybrid-rpi-hetzner](adr-003-hybrid-rpi-hetzner.md) — Hardware topology
- [kubelab-agents](../architecture/components/kubelab-agents.md) — Component spec (updated with phased approach)
- _index — Inbox zone conventions
