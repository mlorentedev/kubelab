---
id: "CONSOLE-002-cross-context-bitacora"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-06-20"
issue: "kubelab#711"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# CONSOLE-002: Cross-context bitácora + Context state model + GitHub adapter

> **Naming**: file lives at `kubelab/specs/CONSOLE-002-cross-context-bitacora/proposal.md`. `<feature-id>` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

> ⚠️ **All sections below are `[AGENT-DRAFT — review before archive]`** — derived from ADR-050 by the agent, not yet ratified by the operator. `/spec archive` will refuse until each tag is resolved (accept / edit / delete). Treat as a strong starting point, not settled truth.

## Why

<!-- from issue #711: CONSOLE-002: cross-context bitácora + Context state model + GitHub forge adapter -->

_[AGENT-DRAFT — review before archive]_

Work is scattered across forges (GitHub, Gitea), boards, and notes with no single picture, so cross-context prioritization and deadlines slip — the core pain ADR-050 names. Module 1 builds the thinnest **demoable vertical** that fixes the panel that hurts daily: a cross-context bitácora backed by a `Context` state model and a GitHub adapter. Building it is what *forces the state model into existence* (isolation, owner, allowed providers, append-only history); defer it and the command center stays an empty shell (the kubelab-console "build last / scope creep" risk) with no live picture for the LLM to prioritize against.

## What

_[AGENT-DRAFT — review before archive]_

Concrete, observable outputs after this PR (slice, not the whole console):

1. **A `Context` entity** (ADR-050 D4) persisted with its four attributes — isolation level, allowed LLM providers + keys, visibility (demoable?), owner — round-tripping through the D7 store (git-canonical + Postgres projection).
2. **Work items belong to a Context** and carry an **append-only** event/transition history (created, re-prioritized, deadline moved, done): re-prioritizing or moving a deadline *appends an event*, it does not mutate state in place — so the LLM later sees trajectory, not just a snapshot.
3. **A GitHub forge adapter** (D3, GitHub only) that ingests a repo's open issues as *forge-backed* board items (forge→board read) and performs a *minimal* board→forge write (status/label) — bounded, not full bidirectional field sync. The board is the **superset**: items may be forge-backed or native.
4. **A queryable cross-context bitácora**: list/show items across contexts with board state (status, priority, dates, context, AI-rank field), via the Go API (per ADR-029) and/or CLI.
5. **Per-context default-deny LLM routing** modeled from day 1 (D5/C1): a Context with no explicit provider policy resolves to local-only (Ollama); cloud requires an explicit per-context grant.

## Out of scope

_[AGENT-DRAFT — review before archive]_

Things this PR explicitly does NOT include (sharp boundary against scope creep):

- **Gitea / GitLab adapters** — incremental against the same interface; M1 is GitHub-only (D3).
- **Console UI surface** beyond the minimum needed to demo the slice — the Astro/React console is built later (kubelab-console "build last").
- **The prioritization rubric *engine*** (D6) — M1 only *carries* the rank field; the LLM-applied rubric is a later module.
- **Federation of external products** (IRIS et al., D2) — the federation contract is out of this slice.
- **Multi-tenant / multi-user** — single-tenant reusing Authelia identity, but the owner/context dimension is carried from day 1 (C6) so it is not a future rewrite.

## Risks / open questions

_[AGENT-DRAFT — review before archive]_

- **✅ RESOLVED (2026-06-20) — State topology (D7): git-canonical + Postgres projection, BOTH in M1.** A write appends an event to git (canonical, append-only per D4, offline-resilient per C3); a **synchronous projector** updates the Postgres-on-VPS projection for queries; **git wins on conflict** and the projection is fully rebuildable by replaying git. Object-storage backup of the git repo per ADR-049. _Chosen over deferring Postgres to a later module — accepts heavier M1 scope (new persistence + migrations + projector on a today-stateless Go API) in exchange for full D7 from the start._
- **✅ RESOLVED (2026-06-20) — Isolation enforcement (C1/D5): single service-layer gate + `context_id` in the model from day 1.** A `resolveContextPolicy(contextID) → {allowedProviders, visibility}` chokepoint is the ONLY path to cloud egress (LLM call, shared-index write, demo export); **default-deny** when a Context has no policy (local-only Ollama). Every item/event carries `context_id` NOT NULL (C6). Home: `apps/api/src/internal/api/middleware.go` or a new `internal/context` policy package.
- _The remaining items below are implementation-time questions, not `tasks.md` blockers._
- **GitHub adapter sync semantics.** Webhook vs poll; idempotency of re-sync; reconciliation of native vs forge-backed items; avoiding board→forge write loops. *Today's lesson (#708/#709): `add-to-project@v2` reported success but silently added nothing — the adapter MUST verify its writes actually land, not trust exit 0.*
- **Per-context provider credentials.** SOPS key layout for per-context API keys (D7) — how keys attach to a Context without leaking across contexts.
- **Demo partition (C2).** The demo/personal Context must be *provably* free of employer/client data to be screen-shareable — how is that proof produced?

## Acceptance criteria

_[AGENT-DRAFT — review before archive]_

- [ ] A `Context` persists all four attributes (isolation, allowed providers+keys, visibility, owner) and round-trips through git + the Postgres projection (automated test).
- [ ] A work item belongs to exactly one Context and accumulates an **append-only** event history; re-prioritizing or moving a deadline appends an event and never mutates prior state in place (test asserts history length grows, prior events immutable).
- [ ] The GitHub adapter ingests a repo's open issues as forge-backed board items (forge→board) **and** writes status/label back to one issue (board→forge), each verified against a real or fixture repo — with the write confirmed by re-reading, not by exit code.
- [ ] A Context with **no** explicit provider policy resolves to local-only (Ollama) on a routing decision; adding a cloud-provider grant flips that resolution — both provable by test (default-deny is enforced, not documented).

> Completeness candidates (Q6) to fold in or reject during `/spec fill` review: adapter re-sync idempotency test; offline-resilience test (git canonical usable with Postgres down, C3); cost/secret guard on per-context cloud keys; regression test that board→forge write cannot loop.

## References

- Tracking ADR: `kubelab/docs/adr/adr-050-cross-context-command-center.md` (module 1 — D3/D4/D5/D7, C1/C2/C3/C6)
- GitHub issue: `kubelab#711`
- Vault: `10_projects/kubelab/11-tasks.md` (backlog entry)
- Related ADRs: `adr-029` (Go API spine + LLM gateway/RAG), `adr-043` (knowledge/memory plane, git-as-bus + pgvector), `adr-048` (platform-consumer boundary), `adr-049` (object-storage backup: Hetzner Box + R2)
- Governance follow-up: `kubelab#712` (CONSOLE-003 — board governance / workflow lifecycle)
