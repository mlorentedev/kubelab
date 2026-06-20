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

> **Ratified 2026-06-20.** `[AGENT-DRAFT]` tags resolved: Why / What / Out of scope / Acceptance
> verified faithful to ADR-050 and accepted; codebase-grounding corrections folded in (see
> "Grounding-corrected prerequisites"); three architecture forks locked (see "Locked decisions").
> Implementation plan in `tasks.md` (DB-first, ~9 atomic PRs).

## Why

<!-- from issue #711: CONSOLE-002: cross-context bitácora + Context state model + GitHub forge adapter -->

Work is scattered across forges (GitHub, Gitea), boards, and notes with no single picture, so
cross-context prioritization and deadlines slip — the core pain ADR-050 names. Module 1 builds the
thinnest **demoable vertical** that fixes the panel that hurts daily: a cross-context bitácora backed
by a `Context` state model and a GitHub adapter. Building it is what *forces the state model into
existence* (isolation, owner, allowed providers, append-only history); defer it and the command
center stays an empty shell (the kubelab-console "build last / scope creep" risk) with no live
picture for the LLM to prioritize against.

## What

Concrete, observable outputs after this module (slice, not the whole console):

1. **A `Context` entity** (ADR-050 D4) persisted with its four attributes — isolation level, allowed
   LLM providers + keys, visibility (demoable?), owner — round-tripping through the D7 store
   (git-canonical + Postgres projection).
2. **Work items belong to a Context** and carry an **append-only** event/transition history (created,
   re-prioritized, deadline moved, done): re-prioritizing or moving a deadline *appends an event*, it
   does not mutate state in place — so the LLM later sees trajectory, not just a snapshot.
3. **A GitHub forge adapter** (D3, GitHub only) that ingests a repo's open issues as *forge-backed*
   board items (forge→board read) and performs a *minimal* board→forge write (status/label) —
   bounded, not full bidirectional field sync. The board is the **superset**: items may be
   forge-backed or native.
4. **A queryable cross-context bitácora**: list/show items across contexts with board state (status,
   priority, dates, context, AI-rank field), via the Go API (per ADR-029).
5. **Per-context default-deny LLM routing** modeled from day 1 (D5/C1): a Context with no explicit
   provider policy resolves to local-only (Ollama); cloud requires an explicit per-context grant.

## Out of scope

Things this module explicitly does NOT include (sharp boundary against scope creep):

- **Gitea / GitLab adapters** — incremental against the same interface; M1 is GitHub-only (D3).
- **Console UI surface** beyond the minimum needed to demo the slice — the Astro/React console is
  built later (kubelab-console "build last"). The M1 query surface is Go API endpoints only; no CLI.
- **The prioritization rubric *engine*** (D6) — M1 only *carries* the rank field; the LLM-applied
  rubric is a later module.
- **Federation of external products** (IRIS et al., D2) — the federation contract is out of this slice.
- **Multi-tenant / multi-user** — single-tenant; `owner`/`context_id` carried from day 1 (C6) so it
  is not a future rewrite, but identity is passed explicitly (see prerequisites — Authelia is not yet
  threaded into the Go API).
- **Async / out-of-process projection** — the git→Postgres projector is synchronous and in-process in
  M1. No separate deployment, watcher, webhook, or CronJob.

## Locked decisions (2026-06-20)

- **Store wiring = DI in `board/` only.** A `Store` interface + constructor injection in the new
  `internal/board/` package; the existing newsletter code (module-level `conf` singleton, free-function
  handlers) is untouched. Rationale: TDD needs an injectable fake; idiomatic Go over entrenching the
  singleton antipattern. Contained deviation.
- **Ordering = DB-first.** After the test harness (PR-0), Postgres infra + atlas schema land first;
  git event-store and the projector follow. Trade-off accepted: persistence infra precedes the first
  green acceptance criterion.
- **Migration tool = atlas** (declarative / schema-as-Go). Captured in **ADR-051** (Postgres as a
  shared data-service + atlas) authored alongside PR-1, since this is a lock-in decision affecting
  cross-instance reuse (Regla del 3).

## Grounding-corrected prerequisites

Codebase audit (2026-06-20) corrected four assumptions the original draft made:

- **No tests + no `go test` in CI.** `apps/api/src` has zero `*_test.go`; `ci-pipeline.yml` runs only
  `go vet` + `go build` for the api app. A failing test is currently invisible. **PR-0 retrofits the
  harness + CI step** before any TDD acceptance criterion can be enforced.
- **Postgres is 100% greenfield.** No `infra.postgres` SSOT, no K8s manifest/StatefulSet, no migration
  tool; the only Postgres in the repo is Gitea's embedded one. D7's "Postgres-on-VPS projection" is new
  infra, not a wiring exercise.
- **Authelia identity is not in the Go API.** It is enforced upstream at Traefik ForwardAuth;
  `middleware.go` is CORS-only. In M1, `owner`/`context_id` is passed **explicitly** (header/param),
  not read from a session. C6's "reuse Authelia identity" has no in-process hook yet.
- **go.mod skew.** Module declares `go 1.23.1`; CI/Docker build on `1.25`. Align the directive when the
  first new dependency lands (atlas / go-git).

## Risks / open questions

- **✅ RESOLVED (2026-06-20) — State topology (D7): git-canonical + Postgres projection, BOTH in M1.**
  A write appends an event to git (canonical, append-only per D4, offline-resilient per C3); a
  **synchronous in-process projector** updates the Postgres projection for queries; **git wins on
  conflict** and the projection is fully rebuildable by replaying git. Object-storage backup per
  ADR-049. Staged across atomic PRs (git store, PG projection, projector as separate PRs), not deferred
  across modules — see `tasks.md` PR roadmap.
- **✅ RESOLVED (2026-06-20) — Isolation enforcement (C1/D5): single service-layer gate + `context_id`
  from day 1.** `resolveContextPolicy(contextID) → {allowedProviders, visibility, owner}` is the ONLY
  path to cloud egress; **default-deny** when a Context has no policy (local-only Ollama). Every
  item/event carries `context_id` NOT NULL (C6). Home: new `internal/board/policy.go` (NOT
  `middleware.go` — see prerequisites; no identity middleware exists to extend).
- _The remaining items are implementation-time questions, not `tasks.md` blockers:_
- **GitHub adapter sync semantics.** Poll-on-demand (`POST /v1/board/sync`) in M1 — no webhook/CronJob.
  Idempotency of re-sync; reconciliation of native vs forge-backed items; avoiding board→forge write
  loops. *Invariant baked in (#708/#709 lesson): the adapter MUST confirm a write landed by re-reading,
  never trust exit 0 — `add-to-project@v2` reported success while silently adding nothing.*
- **Per-context provider credentials.** SOPS key layout for per-context API keys (D7) — how keys attach
  to a Context without leaking across contexts.
- **Demo partition (C2).** The demo/personal Context must be *provably* free of employer/client data —
  how is that proof produced?

## Acceptance criteria

- [ ] A `Context` persists all four attributes (isolation, allowed providers+keys, visibility, owner)
  and round-trips through git + the Postgres projection (automated test).
- [ ] A work item belongs to exactly one Context and accumulates an **append-only** event history;
  re-prioritizing or moving a deadline appends an event and never mutates prior state in place (test
  asserts history length grows, prior events immutable).
- [ ] The GitHub adapter ingests a repo's open issues as forge-backed board items (forge→board) **and**
  writes status/label back to one issue (board→forge), each verified against a real or fixture repo —
  with the write confirmed by re-reading, not by exit code.
- [ ] A Context with **no** explicit provider policy resolves to local-only (Ollama) on a routing
  decision; adding a cloud-provider grant flips that resolution — both provable by test (default-deny
  is enforced, not documented).

> Completeness candidates to fold in or reject during implementation: adapter re-sync idempotency test;
> offline-resilience test (git canonical usable with Postgres down, C3); cost/secret guard on
> per-context cloud keys; regression test that board→forge write cannot loop.

## References

- Tracking ADR: `kubelab/docs/adr/adr-050-cross-context-command-center.md` (module 1 — D3/D4/D5/D7, C1/C2/C3/C6)
- Proposed: **ADR-051** (Postgres as a shared data-service + atlas migration tooling) — authored with PR-1
- GitHub issue: `kubelab#711`
- Vault: `10_projects/kubelab/11-tasks.md` (backlog entry)
- Related ADRs: `adr-029` (Go API spine + LLM gateway/RAG), `adr-036` (shared infra services SSOT, `INFRA_*`),
  `adr-043` (knowledge/memory plane, git-as-bus + pgvector), `adr-048` (platform-consumer boundary),
  `adr-049` (object-storage backup: Hetzner Box + R2)
- Governance follow-up: `kubelab#712` (CONSOLE-003 — board governance / workflow lifecycle)
