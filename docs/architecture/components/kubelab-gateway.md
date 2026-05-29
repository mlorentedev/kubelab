---
id: kubelab-gateway
type: architecture
status: absorbed
absorbed_by: adr-029-intelligence-layer
absorbed_on: "2026-03-28"
created: "2026-05-09"
owner: manu
---

# kubelab-gateway (component spec)

> **Status:** `absorbed` — merged into the unified kubelab Go API (`/v1/llm/*`) per [ADR-029](../../adr/adr-029-intelligence-layer.md) (2026-03-28).
> **Do not implement.** Backlog kept for historical context only.
> **Parent:** kubelab
> **Hardware change:** Ollama moved from Beelink (8GB) to Acemagic-2 (12GB) running Mistral Nemo 12B Q4.
> **Layer:** L1-platform

## Problem (historical)

No unified layer to consume LLMs from the platform. Each service that needs inference (sec-scan, agents, content pipeline) would independently manage API keys, model selection, fallback logic, and cost tracking. Duplicated effort, no cost visibility.

## Solution (historical)

API gateway that exposes an OpenAI-compatible REST API. Routes requests to the cheapest capable backend based on rules: local models (Ollama on Beelink, <32B params) for simple tasks, cloud APIs (GLM-5, Claude) for complex tasks. Single point for API key management, usage tracking, and rate limiting.

## How it was absorbed (ADR-029)

LLM routing was merged into the unified kubelab Go API under the `/v1/llm/*` prefix instead of running as a separate service. Reasons:

- Single binary to deploy/operate at the current scale.
- Shared auth, observability, and config with the rest of the kubelab API.
- Hardware reshuffled: Ollama relocated from the 8GB Beelink (capped at <32B params) to the 12GB Acemagic-2, running Mistral Nemo 12B Q4 — sufficient ceiling for the planned task tiers.

## Tech Stack (historical)

| Component | Technology |
|-----------|-----------|
| Language | Go |
| API | OpenAI-compatible REST |
| Backends | Ollama (local), GLM-5 API, Claude API |
| Deploy | K8s Deployment in kubelab cluster |
| Storage | SQLite (usage tracking) |

## Dependencies (historical)

- kubelab L0 (K3s cluster)
- Ollama on Beelink (K3S-007 ExternalName, already done) — superseded by Ollama on Acemagic-2
- Consumers: [kubelab-agents](kubelab-agents.md), sec-scan

## Decisions (historical)

| Decision | Choice | Reason | Date |
|----------|--------|--------|------|
| Routing | Rule-based (not ML) | Simple, predictable, debuggable | 2026-02-21 |
| Hardware | Beelink for local, APIs for frontier | Beelink has 8GB — models <32B only | 2026-02-21 |
| Audience | Internal first, external TBD | Focus on platform consumers before exposing externally | 2026-02-21 |
| **Form factor** | **Merge into kubelab Go API as `/v1/llm/*`** | **Single binary at current scale; shared auth/observability** | **2026-03-28 (ADR-029)** |

## Milestones (historical, never executed)

| # | Milestone | Done criteria | Status |
|---|-----------|---------------|--------|
| 1 | Proxy pass-through | OpenAI-compatible API forwarding to Ollama | [-] superseded |
| 2 | Multi-backend routing | Ollama + GLM-5 API + Claude API with rule-based routing | [-] superseded |
| 3 | Usage tracking | Per-request logging, cost estimation, rate limiting, API keys | [-] superseded |

## Lifecycle

| Transition | Trigger | Date |
|------------|---------|------|
| → idea | Brainstorm session (GLM-5 + model routing discussion) | 2026-02-21 |
| → spec | Stream H1 fully defined | 2026-02-22 |
| → absorbed | ADR-029 (Intelligence Layer) | 2026-03-28 |

## Historical Backlog (do not implement)

> Originally Stream H1 (BUD-001..004). Functionality replaced by `/v1/llm/*` in the kubelab Go API. Kept for archaeology only.

### LLM Budget & Routing (H1) — historical

- [-] **BUD-001**: Map task types to LLM tiers
  - **Tier 1 (free/local)**: Pollex on Jetson — text polish, spelling, short rewrites
  - **Tier 2 (cheap)**: DeepSeek API — triage, log analysis, scraping, data transforms, content drafts
  - **Tier 3 (premium)**: Claude via MAX plan — architecture review, complex code, PR reviews
- [-] **BUD-002**: Implement LLM router in n8n or OpenClaw
  - Route by task label/category → appropriate LLM backend
  - Fallback chain: local → DeepSeek → Claude (escalate on failure or low confidence)
- [-] **BUD-003**: Token budget and alerting
  - Daily/weekly token budget per tier
  - Alert when approaching limits (80% threshold)
  - Hard stop at budget cap to prevent surprise costs
- [-] **BUD-004**: Cost tracking dashboard
  - Grafana panel: tokens consumed per tier, per task type, per day
  - Monthly cost projection based on rolling average

## Notes (historical)

- Absorbed kubelab `todo.md` Stream H1 (LLM Budget & Routing Strategy, BUD-001..004)
- GLM-5: 744B MoE, MIT license, ~$1/$3.20 per M tokens (5-8x cheaper than Claude)
- Local models: Qwen2.5:7b already on Beelink, ceiling for 8GB RAM
- Reference: SCONE-bench for smart contract audit pricing ($1.22/contract)
