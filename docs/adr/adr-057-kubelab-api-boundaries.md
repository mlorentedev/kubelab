---
id: "adr-057-kubelab-api-boundaries"
type: adr
status: accepted
created: "2026-06-26"
tags: [architecture, api, platform, product-boundary, modular-monolith, repo-structure]
related:
  - adr-029-intelligence-layer
  - adr-053-platform-product-repos
  - adr-048-platform-consumer-repo-boundary
  - adr-034-polyglot-apps-language-per-service
  - adr-045-mlorente-dev-interactive-cv
  - adr-054-web-runtime-config
owner: manu
---

# ADR-057: kubelab API — platform/product boundary and modular-monolith stance

## Status

Accepted — 2026-06-26

Consolidates and makes explicit a boundary that several prior ADRs implied but none stated: what *the kubelab API* is, what may live in it, and when a capability must leave it. Extends [ADR-029](adr-029-intelligence-layer.md) (the "unified kubelab Go API"); guards [ADR-053](adr-053-platform-product-repos.md) (product↔platform separation).

## Context

`apps/api` is a Go (Gin) service. Two forces pull on its identity, and they are unreconciled:

1. **ADR-029 (Accepted)** absorbed the planned `kubelab-gateway` LLM service into *"the unified kubelab Go API"* under `/v1/llm/*`, justified by solo-operator scale: *"single binary to deploy/operate at the current scale; shared auth, observability, and config."* It also simplified-and-absorbed `kubelab-memory`. So the **decided direction is a unified Go API** that hosts shared platform capabilities — not a fleet of per-capability microservices.
2. **Reality / drift**: `apps/api` today contains only **newsletter (Beehiiv), lead-magnet, and health** endpoints. Its README calls it *"the backend for my personal website."* It has **no `/v1/llm` and no `/v1/knowledge`** — the ADR-029 capabilities are decided but unbuilt. So the service is *framed and shaped as web's product backend*, while the architecture intends it as the platform API.

Meanwhile [ADR-053](adr-053-platform-product-repos.md) just separated **products** (own repos — `web` was extracted) from **platform** (stays in kubelab). Without a written rule for what belongs in the central API, the natural drift is: product #2 and #3 each drop their bespoke backend logic into `apps/api` because it is there — turning the unified API into a **god-service / distributed monolith** that re-couples the very products ADR-053 separated. The recurring question ("should the API be central? move it to web? rewrite it in the frontend's language?") is a symptom of this missing boundary.

## Decision

### D1 — `apps/api` IS the unified kubelab platform API (reposition its identity)

It is the L1-platform Go API (single binary), hosted in kubelab, consumed by products over HTTP. Reframe it from "personal-website backend" to "kubelab API" (README, repo framing, service description). It is **not** web's backend that happens to live here; web is one **consumer**.

### D2 — Modular monolith at current scale

One deployable, with clean internal domain modules (`newsletter/`, `llm/`, `knowledge/`, …), each with its own service boundary. This is ADR-029's "single binary at current scale" — **not** a microservice per capability. ADR-034 (language-per-service) stands: spin a *separate* service only when a distinct boundary or language genuinely demands it (as `widget-proxy` did), never by reflex.

### D3 — The platform/product boundary rule (the test)

A capability belongs **in the central API** if and only if it is a **platform capability**:

> **It is consumed by ≥2 products, OR it is genuinely cross-cutting** (auth, LLM, knowledge/RAG, notifications, shared growth/identity).

A capability bespoke to **one** product is **product logic**. During the single-product phase it MAY live in the central API as a clean, isolated module, but its principled home is that product. The deciding axis is **number of independent consumers + lifecycle ownership + boundary cleanliness — never "how heavy" the code is.**

### D4 — Strangler trigger (when a module must leave)

Extract a product module out of the central API into the product's repo when **any** of:

- a **second product** would add its own bespoke logic to the API (never accumulate N products' logic in one binary — that is the antipattern), or
- the module needs an **independent deploy cadence / lifecycle / owner**, or
- the module outgrows a clean boundary.

Until a trigger fires, **do not** decompose preemptively — premature microservices are pure operational cost for a solo operator. The rule prevents the god-service; it does not mandate splitting today.

### D5 — The API boundary is language-agnostic

The contract is HTTP/JSON; a consumer's language is irrelevant to the API's. `web` stays a **static Astro site** ([ADR-045](adr-045-mlorente-dev-interactive-cv.md)) and reaches the API via **same-origin `/api`** ([ADR-054](adr-054-web-runtime-config.md)) through a reverse proxy. Therefore:

- **No rewrite** of the Go API into TypeScript to "integrate it into web." That would force `web` into SSR (discarding its static-nginx model), throw away working Go, and violate [ADR-034](adr-034-polyglot-apps-language-per-service.md).
- **No moving** the API into the `web` repo and **no creating a second API**: `apps/api` already *is* the platform API (mislabeled). You evolve it in place; you don't migrate or duplicate it.

### D6 — Newsletter / lead-magnet disposition (ratified 2026-06-26)

The current newsletter/lead-magnet is the **platform brand list** (the mlorente.dev / personal-brand audience), **not** web-specific product logic — so it **stays in the central API as a platform capability**. Future products will have their **own** lists: when one arrives it either reuses this capability **multi-tenant** (its own list / Beehiiv publication via per-consumer config — preferred, DRY) or, only if its needs genuinely diverge, owns its variant (governed by D4). The *capability* stays central; the *lists* are per-context. So newsletter is a platform capability with one tenant today (the brand), more later.

## Consequences

**Positive**
- One operable API surface at solo scale (ADR-029's single-binary economy preserved).
- A written rule (D3/D4) stops the silent drift into a god-service; products stay decoupled (ADR-053 preserved).
- No wasted Go→TS rewrite; `web` stays static and simple; language independence is explicit.
- `apps/api`'s identity is fixed — future capabilities (`/v1/llm`, `/v1/knowledge`) have a clear, named home.

**Negative / accepted**
- A modular monolith demands module discipline; without it the boundaries rot. D3/D4 are the guard, but they require honoring at each new capability.
- One API = one failure domain and one deploy cadence. Acceptable at current scale; revisit under HA or independent-scaling needs (the D4 triggers cover the structural half).
- The newsletter-as-platform call (D6) is deferred to a business decision; recorded as provisional, not silent.

## Alternatives Considered

- **A microservice per capability** (`llm-svc`, `knowledge-svc`, `newsletter-svc`). Rejected at current scale: per-service deploy/monitor/secure overhead for a solo operator, and ADR-029 already chose the single binary. D4 is the path to services *when scale earns them*.
- **Move `apps/api` into the `web` repo + build a new platform API in kubelab.** Rejected: duplicates effort and misreads the situation — `apps/api` already *is* the platform API, only mislabeled. The product-specific module can stay as a module now and strangle later (D4).
- **Rewrite the API in TypeScript, integrated into the `web` project.** Rejected: breaks `web`'s static model (ADR-045), forces SSR, discards working Go, and contradicts the language-agnostic API boundary (ADR-034 / D5).
- **Leave the boundary unwritten (status quo).** Rejected: that *is* the mechanism by which the god-service forms — product #2's logic lands in `apps/api` "because it's there." The cost of this ADR is one document; the cost of not having it is an 18-month untangling.

## Implementation

Decision-only ADR. Follow-ups are separate tickets/specs:

- Reposition `apps/api` identity (README + service description: "kubelab platform API", not "website backend"). Small.
- Build the ADR-029 platform capabilities (`/v1/llm`, `/v1/knowledge`) as modules — their own specs.
- Confirm the D6 business call (shared vs per-product newsletter).
- Apply D3/D4 when product #2 arrives (or sooner if `web` grows its own dynamic backend).

## References

- [adr-029-intelligence-layer](adr-029-intelligence-layer.md) — the "unified kubelab Go API"; this ADR generalizes its single-binary decision into a boundary rule.
- [adr-053-platform-product-repos](adr-053-platform-product-repos.md) — product↔platform repo split this ADR protects at the API layer.
- [adr-048-platform-consumer-repo-boundary](adr-048-platform-consumer-repo-boundary.md), [adr-034-polyglot-apps-language-per-service](adr-034-polyglot-apps-language-per-service.md), [adr-045-mlorente-dev-interactive-cv](adr-045-mlorente-dev-interactive-cv.md), [adr-054-web-runtime-config](adr-054-web-runtime-config.md).
