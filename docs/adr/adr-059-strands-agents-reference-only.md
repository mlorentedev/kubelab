---
id: "adr-059-strands-agents-reference-only"
type: adr
status: accepted
created: "2026-08-10"
tags: [architecture, agents, ai, evaluation]
related:
  - adr-029-intelligence-layer
  - adr-028-operational-topology
issue: mlorentedev/kubelab#990
owner: manu
---

# ADR-059: Strands Agents — reference only, not adopted

## Status

Accepted — 2026-08-10. Tracks [#990](https://github.com/mlorentedev/kubelab/issues/990) (AI-008).

## Date

2026-08-10

## Context

Evaluate whether Strands Agents (AWS's open-source Python/TypeScript SDK for building AI agents) is worth adopting into kubelab (L1 `kubelab-*`) or dotfiles.

Strands ships as an SDK/framework layer: tool-loop orchestration, steering/guardrail handlers, OpenTelemetry-native observability, and a native MCP client. It is provider-agnostic ("any model, any cloud") and deploys self-hosted via Docker/EKS/Terraform as well as to AWS's managed AgentCore runtime — not a hard AWS dependency, though its documentation, production examples, and operational tooling gravitate toward Bedrock + AgentCore.

kubelab already made the adjacent decision twice before this evaluation started: the 2026-05-15 pivot from OpenClaw to a Nous Research Hermes runtime, and `iris` — a sibling, actively-developed (v0 in execution) self-hosted multi-agent orchestrator (Go motor + NATS + `pi` runtime, Apache-2.0, provider-agnostic) deliberately kept outside the `kubelab-*` namespace as its own product. Both occupy the "adopt a third-party agent SDK" decision space already.

## Reference audit (Regla del 3)

- A production case study — "Building Agents for Platform Engineering: Bedrock & Strands" (DEV305, AWS Summit Madrid 2026) — the reference for real-world Strands deployment patterns: Model Router/Gateway, MCP Gateway, subagents-as-tools, simpler models for subagents (token control), observability-first design.
- Primary-source verification (2026-08-10) against strandsagents.com and AWS Prescriptive Guidance: confirmed deployment targets include Docker/EKS/self-hosted (not Bedrock/AgentCore-exclusive), any-model-provider support, and a native MCP client (`MCPClient`).
- An independent audited framework comparison exists for a different, unrelated project with its own requirements (provider portability against a third-party token cutoff, not a kubelab concern) that also declined Strands, for the same ecosystem-gravity reason found above. Not citable here in detail — private, out of this repo's scope — but its independent arrival at the same conclusion corroborates it.

## Decision

**Do not adopt Strands.** Treat it as a reference implementation only, in the same posture ADR-029 took toward `agent-memory.dev`: no runtime, no dependency, mined for patterns.

No open gap exists at either candidate layer:

- **L1 `kubelab-*`**: the self-hosted multi-agent orchestration niche is already `iris`'s, by deliberate design (its own repo, its own Apache-2.0 license, its own runtime choice already iterated once).
- **dotfiles**: personal agent scripting is already covered by Claude Code (interactive) and n8n (scheduled/triggered), with no unmet need surfaced during this evaluation.

Hardware is not a differentiator either way: Strands is provider-agnostic like kubelab's existing agent tooling, so the absence of a GPU node does not block it — but per ADR-028 there is no free always-on slot (VPS / aws1 / RPi3) for a fourth agent runtime regardless of framework choice.

### Where to mine value (if `iris` or the knowledge-plane work needs it)

| Pattern | Strands' shape | Where it could apply |
|---|---|---|
| Steering/guardrail handlers | Intercept and validate agent decisions before execution | `iris`'s two-stage verification gate (coder self-check + QA agent) — a second design to compare against |
| OTel-native observability | Built-in distributed tracing per agent run | `iris`'s SDD-029 (OTel observability) — a worked reference to check against, not a library to import |
| MCP client conventions | `MCPClient` abstraction over Streamable HTTP/stdio | Cross-check against ADR-043's plane-ii consumer wiring (Hermes/coding-agent MCP tools) when that implementation resumes |
| Model Router/Gateway pattern (DEV305) | A control-plane component separate from the agent loop | Already kubelab's own direction (LLM gateway absorbed into the Go API, ADR-029 §2) — corroborates, does not change, the existing design |

## Consequences

### Positive

- Closes an open evaluation front with evidence rather than leaving it an unexamined "maybe."
- Confirms, via an independent framework rather than internal precedent alone, that the 2026-05-15 orchestrator pivot and `iris`'s existence are a sufficient answer to "should we adopt a third-party multi-agent SDK." No re-litigation needed unless a trigger below fires.
- A concrete reference table exists for `iris`'s observability and verification-gate design work, cheaper than re-deriving these patterns from scratch.

### Negative

- None identified — this is a non-adoption decision with no migration or deprecation cost.

### Neutral

- Strands' own maturity and AWS-ecosystem trajectory are not re-assessed by this ADR; if `iris`'s `pi` runtime is later found inadequate, Strands re-enters the option space fresh (see triggers).

## Triggers to Reopen

- `iris`'s `pi` runtime proves inadequate for a concrete, encountered gap (not speculative).
- A GPU node materializes, changing the local-inference calculus this evaluation assumed static.
- A genuine AWS-hosted deployment target emerges for kubelab or a client engagement, where Strands' AgentCore integration would be load-bearing rather than incidental.

## References

- Issue: [#990](https://github.com/mlorentedev/kubelab/issues/990) — AI-008, Strands Agents evaluation
- [ADR-029](adr-029-intelligence-layer.md) — Intelligence layer (structural precedent: "reference only, not adopt" treatment of agent-memory.dev)
- [ADR-028](adr-028-operational-topology.md) — Operational topology (always-on/on-demand budget)
- strandsagents.com — official docs, deployment targets, MCP support
- AWS Prescriptive Guidance — Strands Agents framework overview
- DEV305, "Building Agents for Platform Engineering: Bedrock & Strands" — M. Fontanilla, AWS Summit Madrid 2026
