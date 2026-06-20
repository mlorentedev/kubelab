---
id: "adr-049"
type: adr
status: accepted
owner: manu
date: "2026-06-19"
issue: "kubelab#703"
tags: [architecture, decision, edge, cloudflare, workers, object-storage, backblaze-b2, cloudflare-r2, finops, lock-in, blueprint, substrate]
depends_on: [adr-042-reference-architecture, adr-048-platform-consumer-repo-boundary, adr-029-intelligence-layer, adr-043-unified-knowledge-memory-plane, adr-045-mlorente-dev-interactive-cv]
created: "2026-06-19"
---

# ADR-049: Edge & Object-Storage Placement Doctrine (Cloudflare Workers + B2/R2)

## Status

Accepted — 2026-06-19. Output of an `/architecture-session`. **Supersedes the Backblaze B2 portions of [[adr-023-hub-spoke-multicloud-gitops|ADR-023]] (the "MinIO → B2" 3-2-1 leg) and [[adr-024-pvc-backup-strategy|ADR-024]] (Phase 5 "Velero + B2")** — see D3.

## Context

The question: where do **Cloudflare Workers** (edge compute) and **cheap S3-compatible object storage** (Backblaze B2 / Cloudflare R2) fit the KubeLab ecosystem, and what rule governs their adoption so the choices lay a coherent foundation for the startup?

This is not greenfield. Three prior artifacts already stake out positions:

- **`research-cloudflare-fit.md` (2026-06-11, vault `10_projects/kubelab/40-research/`)** — a thorough, price-verified audit of the entire Cloudflare product line against the showcase. Conclusion: *Free zone + Workers Paid ($5/mo) + R2 free tier ≈ $5/mo; keep Hetzner Storage Box for Borg; skip Pro.*
- **Hermes ADR-004 (`80_agents/hermes-nan/decisions/`, proven in prod 2026-06-14)** — an age-encrypted, `rclone`-to-object-store backup, **dormant until provisioned**, with a phased `R2/S3/B2` destination. A reusable, proven pattern for "encrypted offsite backup to object store."
- **ADR-023 / ADR-024** — the 2026-03 backup design that wrote Backblaze B2 into the 3-2-1 strategy (~$0.50/mo, Velero/MinIO replication). **Zero lines wired** in `infra/terraform`, `toolkit`, or `infra/k8s` — a paper decision.

The governing tension is the **anti-lock-in paradox**: per ADR-031 the brand sells *"Platform Engineering for AI Workloads — escape the hyperscaler, self-manage your stack."* If the reference architecture itself *depends* on a proprietary edge runtime, the pitch eats itself. The resolution must classify these technologies deliberately, not adopt them wholesale.

State verified at decision time: Cloudflare is used at the **minimal level** — authoritative DNS only, **`cf-proxied:false` on every record** (no CDN, no WAF, no Workers in the path). MinIO is the live S3 store. The vault is not synced to the corporate workstation used this session; the prior-art docs were read via the GitHub API (`mlorentedev/knowledge`).

## Reference audit (Regla del 3, ADR-015)

The decision affects cross-instance reuse (the client-replicable blueprint of ADR-042), so the audit gate fires. It is substantially **pre-satisfied** by existing research.

| Dimension | R1 · `research-cloudflare-fit` (2026-06-11) | R2 · Hermes ADR-004 (backup, prod-proven) | R3 · ADR-042/048 (governance) |
|---|---|---|---|
| Object store verdict | R2 free 10GB for critical subset; **Hetzner Box + Borg for bulk** (4× cheaper at 1TB, ransomware snapshots, speaks SSH/Borg); B2 **not** selected | `rclone` to R2/S3/B2, age-asymmetric, `sqlite .backup` for consistency, dormant-until-provisioned | "State off compute nodes (object store + Postgres)" (C3); object-store is a *role* |
| Edge compute verdict | Workers fit **HIGH** for glue/forms/gating; KV/DO/D1 caveat "runtime lock-in"; Pro plan rejected (duplicates CrowdSec showcase) | n/a | Go API is THE gateway (ADR-029 "gateway absorbed into API"; ADR-048 "not a web BFF") |
| Private connectivity | "AI Gateway/edge needs public HTTPS upstream → VPN-only Ollama unreachable" | n/a | Go API bridges public→private (lives on the VPS with pgvector access) |

**Capability frontier (newer than R1):** Cloudflare **Workers VPC** (`vpc_service` binding over a Tunnel) + **Hyperdrive** now let a Worker reach a private origin without public exposure — which would invalidate R1's "edge can't see private services" blocker. But Workers VPC is **beta** (public-to-private routing in closed beta, GA targeted Q4 2026), so it is a watch/spike, not load-bearing.

### Divergence log

- **Intersection (blueprint candidates):** "state off compute nodes via an object-store *role*" (R1+R2+R3); S3 API as the portable contract (R1+R2). These are vendor-agnostic and safe in the blueprint.
- **Lock-in (NOT blueprint):** Cloudflare stateful primitives KV/DO/D1/Queues (R1 caveat); a second edge gateway that duplicates the Go API (R3). Substrate/consumer only, or mental-model only.
- **Strategic finding:** the dividing line that resolves the paradox is **statefulness + gateway-role**, not the vendor.

## Constraints

Inherits ADR-042 C1–C12. New constraints formalized this session:

| # | Constraint | Origin |
|---|---|---|
| C13 | Anything load-bearing in the *blueprint* must be vendor-agnostic (named by role, not vendor) | the paradox + ADR-042 C1 |
| C14 | Vendor *stateful* primitives never enter the blueprint and never become load-bearing in the substrate | R1 caveat + ADR-043 |
| C15 | The Go API is the single platform gateway; edge functions never absorb auth/routing | ADR-029 + ADR-048 |
| C16 | Enabling any edge feature is a posture change (proxy-on) that must preserve CrowdSec as the WAF brain and the real client IP | conflict audit D |

## Options Considered

**Object-store offsite target** (C13/C14):

| Option | Summary | Verdict |
|---|---|---|
| Keep B2 (ADR-023 as written) | "MinIO → B2" bulk 3-2-1 leg | Rejected — superseded by R1 (Hetzner Box wins bulk 4× + snapshots) |
| Retire B2 entirely | Hetzner Box (bulk) + R2 (critical subset); large S3 artifacts → R2-paid / Hetzner Object Storage | **Chosen** |
| R2-only | Cloudflare-native, zero egress | Rejected — 10GB free cap can't hold bulk; couples bulk to one vendor |

**Edge compute** (C14/C15):

| Option | Summary | Verdict |
|---|---|---|
| Stateless-edge-only | Workers for static-adjacent edge concerns; KV/DO/D1 = mental model | **Chosen** (doctrine) |
| Allow stateful where convenient | KV/DO/D1 for edge state | Rejected — lock-in, dents portability claim |
| No Workers, declarative CF only | Turnstile + rules + WAF | Rejected — leaves free value (static-resilience, signed-URLs, AI Gateway) on the table |

## Decision

A placement doctrine (D1–D5) plus a conflict-checked adoption plan.

- **D1 — Blueprint names roles; substrate picks vendors.** Roles: `tier-object-store`, `tier-edge-function`, `tier-offsite`. A client on AWS instantiates `tier-edge-function` with CloudFront Functions; the KubeLab substrate uses Workers. The blueprint never depends on a concrete vendor.
- **D2 — The lock-in line is *state*.** S3 (R2/B2) = portable commodity, admissible even inside the blueprint. Stateless Workers = portable concept, admissible in substrate/consumer, never a blueprint dependency. **KV / Durable Objects / D1 / Queues = real lock-in → mental model only** (consistent with ADR-043 keeping the knowledge plane self-hosted on pgvector).
- **D3 — Storage in 3 tiers; B2 retired.** `tier-offsite` bulk = Hetzner Storage Box + Borg; `tier-offsite` critical subset = R2 (zero egress, free 10GB, reusing the Hermes ADR-004 age+rclone pattern); large S3 artifacts (model weights/datasets for the GPU showcase) = R2-paid or Hetzner Object Storage. **Backblaze B2 leaves the ecosystem**; the B2 portions of ADR-023/ADR-024 are superseded.
- **D4 — Proxy-on is a posture change, not a toggle.** Tracked as CF-PROXY-001 (#704). CrowdSec stays the WAF brain; Traefik must trust Cloudflare ranges and read `CF-Connecting-IP` before any edge feature ships.
- **D5 — The Go API is THE platform gateway** (ADR-029/ADR-048). Edge Workers are limited to edge-only concerns (CDN cache, bot pre-filter, signed-URL minting, Turnstile) and never absorb auth, routing, or knowledge/LLM proxying.

**Adoption plan (conflict-checked):**

- **Adopt (clean):** Turnstile for the lead-magnet form (WEB-002e #570) · R2 critical-subset offsite (BACKUP-043 #596) · retire B2 · signed-URL Worker for gated R2 downloads (low priority, after R2).
- **Prerequisite:** CF-PROXY-001 (#704) gates all edge features.
- **Reconcile (scope-trim, not new):** Cloudflare **AI Gateway** = a $0 *supplementary* cost ledger on the **cloud LLM leg** (OpenRouter/NaN); IDP-026 (#379) keeps the Ollama leg and remains a proof-surface dashboard (ADR-045 "demonstrate the owned stack"). Cloudflare as **CDN in front of the K3s origin** for resilience — without moving hosting (SSE chat is uncacheable; static assets are cacheable).
- **Park:** Workers VPC + Hyperdrive (overlaps the Go API gateway per D5; beta until ~Q4 2026 — revisit if a non-API edge→private path emerges).
- **Drop (collisions):** Cloudflare **Email Routing** (collides with Zoho MX + MAIL-001 #268) · **Workers static hosting** for mlorente.dev (collides with ADR-045's locked Docker→nginx→K3s pipeline + the self-hosting showcase) · edge BFF/auth/routing (D5).
- **Skip (re-confirmed):** Pro plan · Workers AI · Containers · Tunnel-for-staging · KV/DO/D1 as load-bearing.

## Conflict audit

The session ran an explicit collision check against installed/planned/running systems before persisting:

| # | Proposal | Collides with | Resolution |
|---|---|---|---|
| A | CF Email Routing | Live Zoho MX + MAIL-001 (#268); Email Routing needs CF MX, can't coexist with Zoho on one domain | **Dropped** |
| B | Workers static hosting (mlorente.dev) | ADR-045 §1 locks "keep Docker→nginx→K3s"; the self-hosted site is proof-surface PS1 | **Dropped** (use CDN-in-front instead) |
| C | AI Gateway as the LLM cost dashboard | IDP-026 (#379) already plans this in Grafana; ADR-045 §36 prefers the owned stack; AI Gateway sees only the public leg | **Reframed** as a $0 cloud-leg supplement |
| D | Any edge feature (proxy-on) | CrowdSec `clientTrustedIPs` + Authelia `X-Forwarded-For` read real IP after 1 hop; CF adds a hop | **Prerequisite** CF-PROXY-001 (#704) |

## Rationale

Knowing what *not* to homogenize is the senior signal ADR-042 already established; this ADR extends that discipline from clusters to the edge and storage tiers. The doctrine preserves the ADR-031 anti-lock-in pitch by construction: the blueprint is portable (roles, S3 API), the convenient-but-proprietary pieces (Workers compute) live only in the substrate/consumer layer, and the genuinely sticky pieces (KV/DO/D1) never become load-bearing. Retiring B2 follows the operator's own newer evidence rather than a stale paper decision, and consolidating the encrypted-backup mechanism on the proven Hermes pattern means one backup doctrine across the whole agent + platform fleet.

## Consequences

**Positive:** resolves the anti-lock-in paradox with a reusable rule (the decision record is itself a portfolio artifact per ADR-042); ends the B2-vs-R2 and B2-vs-Hetzner-Box ambiguity; the conflict audit prevented two collisions (Email Routing, static hosting) before any code; the Go API's gateway role is protected from edge cannibalization.

**Negative:** enabling edge features is gated on the non-trivial CF-PROXY-001 posture change; Cloudflare convenience features still create *operational* (not architectural) coupling in the substrate; Workers VPC beta means the "edge reaches private origin" capability is watch-only for now.

**Neutral:** AI Gateway becomes an optional free supplement; the homelab/VPS remains the degenerate substrate instance; existing Terraform DNS ownership is unchanged (proxied flag is just another managed attribute).

## Implementation / backlog

- **Now:** this ADR + EDGE-001 (#703) + CF-PROXY-001 (#704).
- **Next (gated by #704):** Turnstile (#570); R2 critical-subset offsite (#596, reuse Hermes age+rclone); mark the B2 legs of ADR-023/ADR-024 superseded.
- **Later:** signed-URL Worker for gated R2 downloads; AI Gateway on the cloud LLM leg (supplement to IDP-026 #379); CDN-in-front of the K3s origin.
- **Parked:** Workers VPC + Hyperdrive (revisit ~Q4 2026 GA).

## References

- Research: `10_projects/kubelab/40-research/research-cloudflare-fit.md` (2026-06-11, price-verified)
- Pattern: Hermes `80_agents/hermes-nan/decisions/004-encrypted-state-backup.md` (age + rclone, prod-proven 2026-06-14)
- Supersedes B2 portions of [[adr-023-hub-spoke-multicloud-gitops]], [[adr-024-pvc-backup-strategy]]
- [[adr-042-reference-architecture]] (blueprint vs substrate), [[adr-048-platform-consumer-repo-boundary]] (platform vs consumer), [[adr-029-intelligence-layer]] (gateway absorbed into API), [[adr-043-unified-knowledge-memory-plane]] (self-hosted knowledge plane), [[adr-045-mlorente-dev-interactive-cv]] (owned-stack showcase)
- Tickets: EDGE-001 (#703), CF-PROXY-001 (#704), BACKUP-043 (#596), WEB-002e (#570), IDP-026 (#379), MAIL-001 (#268), IDEAS-002 (#702)
- Cloudflare Workers VPC (beta): developers.cloudflare.com/workers-vpc · Workers pricing: developers.cloudflare.com/workers/platform/pricing
