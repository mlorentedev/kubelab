---
id: "adr-050"
type: adr
status: accepted
owner: manu
date: "2026-06-20"
issue: "kubelab#706"
tags: [architecture, decision, command-center, console, productivity-os, multi-context, federation, forge-agnostic, bitacora, llm, isolation]
depends_on: [adr-026-idp-evolution, adr-028-operational-topology, adr-029-intelligence-layer, adr-042-reference-architecture, adr-043-unified-knowledge-memory-plane, adr-048-platform-consumer-repo-boundary, adr-049-edge-object-storage-placement-doctrine]
created: "2026-06-20"
---

# ADR-050: Cross-Context Command Center (kubelab matured into a personal operations console)

## Status

Accepted — 2026-06-20. Output of an `/architecture-session`. Builds on ADR-026 (IDP 4-layer), ADR-029 (intelligence layer), ADR-042 (reference architecture), ADR-043 (knowledge/memory plane). Gives the `kubelab-console` component spec (2026-02-21) its concrete shape and **absorbs DASH-001** (Homepage cockpit). **Retires the GitHub Projects v2 _board_ as the task surface** (see D3) while preserving GitHub/Gitea _issues_. **Supersede-candidate for the Open WebUI operator-console role** of ADR-042 (see D5). Triggers a follow-up review of the cross-project bitácora governance (issue tracking currently spans `kubelab` / `iris` / `knowledge` GitHub Projects).

## Context

The session began as "replace GitHub Projects as the bitácora" and converged, through brainstorming, on something larger: a single **cross-context command center** — the operator's one place to run all work across separate life-contexts (personal projects, employer work, freelance/client work). The driver is constant context-switching: with work scattered across forges, boards, and notes, nothing has a single picture, so prioritization and deadlines slip. Centralizing gives an LLM a live photograph of all work so it can help prioritize, schedule, and orchestrate, with multi-channel task capture (chat, email, Telegram) and federation of the operator's own products (IRIS today, others later).

This is **not greenfield**. The "productivity OS" is the convergence of eight prior artifacts that already decided ~80% of it but live dispersed and mostly unbuilt:

- **ADR-029** — intelligence layer: the Go API absorbs the LLM gateway and RAG ("one binary, one deployment"); Ollama-local + OpenRouter routing; n8n as the automation layer. Names "no automation layer — task management is manual" as gap #1.
- **ADR-043** — unified knowledge/memory plane: git-as-bus + pgvector + `POST /v1/knowledge/search`, one index for all consumers. The substrate for "the LLM has a picture of everything."
- **ADR-042** — reference architecture; Open WebUI as the operator console.
- **kubelab-console** (component spec) — the "visual convergence point", Astro + React islands, portfolio kanban, Stream G wiki (Quartz). Marked "build LAST: a dashboard without data is an empty shell."
- **DASH-001** — the Homepage cockpit at `home.kubelab.live` (done 2026-03-26).
- **ADR-048** — platform-vs-consumer boundary: products are independently extractable (own repos).
- **ADR-007** (superseded → IRIS / `adr-002-orchestrator-architecture`) — the original "delegate tasks to agents" idea, now realized as IRIS.
- **IRIS** `00-context` — the live federation precedent: a standalone product that _consumes_ kubelab infra (Traefik, Postgres, Authelia forwardAuth, observability) and deploys as a kubelab app, with its own repo, license, and release cycle. "NOT a kubelab service."

State verified at decision time: on a clean `feat/adr-050-command-center` branch off `master` (`acb2b02`, ADR-049 merged via #705). The intelligence layer (pgvector, embedding pipeline, search API), Open WebUI, and the console are **specced but unbuilt** — so there is no sunk cost in scattered implementations.

## Reference audit (Regla del 3, ADR-015)

The decision affects cross-instance reuse (a federation/module contract that will serve N products and N forges), so the gate fires. Substantially pre-satisfied by the brainstorm.

| Dimension | R1 · Industry consoles (Backstage / Linear / Odysseus) | R2 · Self-hosted trackers (Vikunja / Plane / Huly / Leantime) | R3 · Internal federation precedents (IRIS / mlorente.dev / DASH-001) |
|---|---|---|---|
| Convergence model | Backstage = portal over many backends (rejected by kubelab-console spec: "too heavy for a single dev"); Odysseus = monolith bundling ~8 capabilities incl. tasks | Boards own orchestration metadata; forges/integrations are synced sources (Linear/Plane GitHub sync); Leantime = cognitive-load-first UX | IRIS = standalone product behind shared Authelia + kubelab infra; mlorente.dev = independent repo; DASH-001 = read-only cockpit |
| Build vs adopt | Adopt-and-skin (Odysseus self-hostable) vs build bespoke | Vikunja chosen once (ADR-007) for "compose, don't build" | Federate (own repo, own deploy), never absorb (ADR-048) |
| Forge coupling | GH Projects v2 = GitHub-only board | Trackers are forge-agnostic; forge is one integration among many | Gitea already self-hosted; multi-forge is a real future |

### Divergence log

- **Intersection (reusable core):** a **federation contract** (shared SSO + kubelab infra, the IRIS pattern) and **Context-as-primitive**. Forge-agnostic board state owned by the orchestration layer, forges as synced sources. These belong in the core.
- **Unique (NOT core):** each product's domain (IRIS = coding-agent factory with a QA gate) — federated, never compiled in. Each forge's API quirks — hidden behind a per-forge adapter.
- **Strategic finding:** the dividing line is **orchestration-metadata vs work-item-source**. The command center owns orchestration (status/priority/dates/context/rank); forges own code + issues + PRs. GH Projects v2 conflates the two and is GitHub-locked — which is exactly why it cannot be the board for a multi-forge operator.

## Constraints

| # | Constraint | Origin |
|---|---|---|
| C1 | **Per-context isolation, default-deny.** A work/client context's data must never reach cloud LLMs, the shared index, or a demo without an explicit per-context policy. | User statement (employer/client confidentiality); same design as C2 |
| C2 | **Demoability.** There must be a personal/demo partition provably free of employer/client data, screen-shareable in interviews/talks. | User statement (portfolio); kubelab-console "showcase + ops" dual purpose |
| C3 | **Offline / always-on.** The command chain cannot sit behind an on-demand node — it must stay reachable when the homelab is powered down. | ADR-028 (on-demand topology); ADR-043 (vault offline guarantee) |
| C4 | **Federate, not absorb.** External products stay independently deployable/extractable; the console integrates them via contract, never by compiling them in. | ADR-048 (platform-consumer boundary) |
| C5 | **Prioritization is an explicit rubric the LLM applies**, not a black box. The ranking policy is a first-class, inspectable artifact. | User statement; trustworthiness + explainability |
| C6 | **Single-tenant now, owner/context dimension from day 1.** Reuse the Authelia identity; carry the owner/context column so multi-user productization is a later increment, not a retrofit. | User statement; avoids cross-tenant rewrite cost |

## Options Considered

| Option | Summary | Verdict |
|---|---|---|
| **A — Federate-only (no build)** | Adopt Vikunja/Plane + Homepage + Open WebUI, wire them together. | Rejected: the valuable spine (intelligence layer) is unbuilt; wiring N unbuilt services is more work than one coherent app. No single surface. |
| **B — Build bespoke from scratch** (Odysseus-style monolith) | Reimplement chat, research, email, tasks, etc. in a new app. | Rejected: reimplements mature engines (Ollama, pgvector, n8n); contradicts ADR-029 consolidation-into-the-Go-API; the never-finishing trap. |
| **C — kubelab matured = modular monolith that federates** | Go API spine (per ADR-029) + Astro console surface; owns state/UI/orchestration, calls external engines, federates external products. | **Chosen.** No sunk cost, consolidation is kubelab's own doctrine, preserves the extractable-products portfolio. |
| **D — Fix method only, defer tooling** | Impose WIP/priority discipline on current GH Projects; build nothing. | Rejected as the endpoint (does not deliver the cross-context picture or showcase), but adopted as a principle: build module 1 for daily use first. |
| **Board sub-decision: replace vs federate GH Projects** | Replace = command center owns a forge-agnostic board; federate = keep GH Projects, adapter on top. | **Replace** (D3): GH Projects v2 is GitHub-only and cannot be the board across Gitea/GitLab. |

## Decision

**D1 — App = kubelab matured, not a new project.** The command center is the **Go API** (the spine, where ADR-029 already placed the LLM gateway + RAG) plus an **Astro + React-islands console** (the single surface). It absorbs the DASH-001 cockpit. Framing it as "finishing kubelab" rather than "starting a productivity OS" is deliberate: convergence of the existing roadmap, not a new open-ended project.

**D2 — Modular monolith that FEDERATES, not absorbs.** External products integrate via shared Authelia SSO + kubelab infra (the IRIS precedent: own repo, own deploy, behind the same auth), never by being compiled into the monolith. The console **delegates coding work to IRIS** (the realization of ADR-007's "delegate to agents"); it does not rebuild agent orchestration. n8n is called for channel ingestion + cron, not absorbed. Inside the app lives the operator's differential value (state model, single UI, prioritization logic, context/isolation model); outside is orchestrated what is already mature (Ollama, Postgres/pgvector, n8n, Authelia, vault/Quartz).

**D3 — Forge-agnostic orchestration board; GitHub Projects v2 retired.** The command center owns the **board state** — status, priority, dates, milestones, context assignment, AI rank — in its own store. **Forges (GitHub, Gitea, GitLab) are synced issue/PR _sources_ via per-forge adapters.** GitHub/Gitea _issues_ are preserved, so SDD `/spec init` gating on an open issue survives. Sync is **bounded**: forge→board read (webhook/poll) + minimal board→forge write (state/label); **not** full bidirectional field sync. Rationale: GH Projects v2 is GitHub-only and can never hold a Gitea/GitLab item, so a multi-forge operator is _forced_ to own the board. The board is the **superset**: an item may be **forge-backed** (dev work synced from an issue/PR) or **native** (a personal / employer / client task with no forge issue at all). Milestones and dates therefore span both forges (GitHub + Gitea + GitLab) _and_ non-dev contexts — which no forge-native board (per-GitHub GH Projects) can do. Module 1 ships the **GitHub adapter only**; Gitea/GitLab adapters are incremental against the same interface.

**D4 — `Context` is the central primitive.** Each Context (personal / employer / freelance-client / demo) carries: isolation level, allowed LLM providers + keys, visibility (demoable?), and owner. **Work items and PRs belong to a Context** and carry an **append-only event/transition history** (created, re-prioritized, deadline moved, done) so the LLM sees _trajectory_ (slippage, real-vs-estimated duration, velocity), not just a snapshot. Federated products declare which Contexts they serve.

**D5 — Per-context LLM routing, default-deny.** The `Context → allowed-providers` policy is a **security control**: a Context with no explicit policy is local-only (Ollama). Cloud providers require an explicit per-context grant; employer/client contexts default to local-only. Routing is per-context (cloud + local, chosen by the work at hand), not a single global rule. The console's chat panel makes the standalone Open WebUI operator-console role (ADR-042) a **supersede-candidate** — confirm during AI-003.

**D6 — Prioritization = explicit rubric the LLM applies.** The ranking policy (deadline proximity, context/energy fit, dependencies, value, WIP-aging) is a first-class, inspectable artifact; the LLM is the _interface_ to it, not the authority. This makes the recommendation trustworthy enough to use daily and explainable in a talk ("here is my prioritization model; the LLM executes it").

**D7 — State: git + Postgres + object-storage backup.** Canonical state = **git** (offline-resilient, like the vault — satisfies C3) + **Postgres-on-VPS** projection (queryable + event log) + **object-storage backup per ADR-049** (Hetzner Storage Box + R2). Single-tenant reusing the Authelia identity, but the data model carries an **owner/context dimension from day 1** so multi-user productization is a later increment, not a retrofit (C6). Per-context provider credentials (API-key orchestration) flow through SOPS.

## Rationale

- **No sunk cost:** the intelligence layer is unbuilt, so building one coherent app beats wiring N services that do not yet exist.
- **Consolidation is kubelab's own doctrine:** ADR-029 already chose "one binary, one deployment" over microservices at single-operator scale.
- **Federate-not-absorb** preserves the extractable-products portfolio (ADR-048) and reuses the proven IRIS integration pattern.
- **Replace-the-board is forced**, not preferred: a multi-forge future (Gitea already self-hosted) disqualifies the GitHub-only GH Projects v2.
- **Isolation == demoability:** the same partition that keeps employer/client data off cloud is the one that is screen-shareable — the uncomfortable constraint (C1) and the attractive one (C2) are the same design.
- **Build for daily use:** the most authentic demo is something the operator depends on, which also guards against breadth-for-show.

## Consequences

### Positive

- One command center across all contexts; the LLM gets a live cross-context picture for prioritization and scheduling.
- Forge-agnostic (GitHub / Gitea / GitLab) orchestration; not locked to one vendor's board.
- A senior/staff-level portfolio and talk piece that is also the daily driver — `kubelab-console` finally gets concrete shape.
- Reuses Authelia, Postgres/pgvector, Ollama, n8n, vault/Quartz — minimal new infra.

### Negative

- Retiring GH Projects v2 loses its free automations (`add-to-project.yml`, `bitacora-status.yml`) and native UI; lifecycle of those workflows must be reconsidered once the board moves.
- The command center now owns forge sync — bounded, but real ongoing maintenance.
- This is the single largest build on the roadmap; needs brutal MVP discipline (ship module 1 only, one panel at a time — the kubelab-console "scope creep" risk).

### Neutral

- The Open WebUI role is likely superseded by the console chat panel (confirm in AI-003).
- Cross-project bitácora governance (multi-repo GitHub Projects across `kubelab` / `iris` / `knowledge`) needs a separate reconciliation; this ADR does not decide it.
- n8n remains for channel ingestion + cron; the LLM routing and RAG continue to live in the Go API per ADR-029/043.

## Next steps

- `/spec init` for **module 1**: cross-context bitácora + `Context` state model + GitHub forge adapter (the demoable vertical slice; the panel that hurts today and forces the state model).
- Open a bitácora tracking issue for this ADR and backfill `issue:` in the frontmatter.
- Follow-up architecture review: reconcile cross-project bitácora governance.
- Revisit `add-to-project.yml` / `bitacora-status.yml` once the board migrates.

## References

- ADR-026 (IDP evolution, 4-layer model)
- ADR-028 (operational topology: always-on vs on-demand)
- ADR-029 (intelligence layer: Go API monolith, Ollama + OpenRouter routing, n8n automation)
- ADR-042 (reference architecture; Open WebUI operator console)
- ADR-043 (unified knowledge/memory plane: git-as-bus + pgvector + `/v1/knowledge/search`)
- ADR-048 (platform-consumer repo boundary; extractable products)
- ADR-049 (edge & object-storage placement doctrine; Hetzner Box + R2)
- ADR-007 (Vikunja + n8n + OpenClaw; superseded → IRIS)
- `kubelab-console` component spec (vault `30-architecture/components/`)
- DASH-001 (Homepage cockpit)
- IRIS `00-context` (federation precedent)
