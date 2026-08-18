---
id: lesson-281-edge-vendor-placement-statefulness-is-the-loc
type: lesson
status: active
created: "2026-06-19"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# Edge/vendor placement: statefulness is the lock-in line — and audit collisions before persisting a decision

**Context:** ADR-049 architecture session — deciding how Cloudflare Workers + S3-compatible object storage (Backblaze B2 / Cloudflare R2) fit an IDP whose brand (ADR-031) sells "escape hyperscaler lock-in" while the infra itself is the client-replicable reference architecture (ADR-042). Strong prior art existed: a price-verified `research-cloudflare-fit.md` (2026-06-11, vault) and the prod-proven Hermes age+rclone backup (Hermes ADR-004).

**Problem:** Two traps. (1) Adopting a proprietary edge runtime wholesale silently contradicts the anti-lock-in pitch the architecture is meant to demonstrate. (2) Even a thorough, price-verified research doc recommended adoptions that **collided with already-locked decisions** — CF Email Routing needs Cloudflare MX, which cannot coexist with the live Zoho MX (MAIL-001 #268); and "host mlorente.dev on Workers static" contradicts ADR-045's locked Docker→nginx→K3s pipeline and the self-hosting showcase (the site running on its own K3s IS proof-surface PS1). Verified-pricing ≠ collision-checked: an upstream analysis written in isolation does not know your locked ADRs.

**Solution:** Two reusable rules. (1) **Placement doctrine** (ADR-049 D1–D5): the blueprint names *roles* (`tier-object-store` / `tier-edge-function` / `tier-offsite`); the substrate picks *vendors*; the lock-in line is *state* — commodity S3 (R2/B2) and stateless Workers are portable and admissible (S3 even inside the blueprint), but vendor *stateful* primitives (KV / Durable Objects / D1 / Queues) stay a mental model only and never load-bearing (the knowledge plane stays self-hosted on pgvector, ADR-043); and the single platform gateway (the Go API, ADR-029/048) is never cannibalized by edge functions. (2) **Conflict audit before persisting** (Phase E of an architecture session): before writing the ADR, run an explicit collision check against installed + planned + running systems — existing ADRs, open bitácora tickets, live config — and surface it as a table. Here it caught the two collisions above and reframed a third (CF AI Gateway overlaps the IDP-026 Grafana dashboard → demoted to a free cloud-leg supplement). Corollary: prefer the operator's newer evidence over a stale paper-decision — B2 was retired (superseding the B2 legs of ADR-023/024) for Hetzner Box + R2, per the 2026-06-11 research.

**Tags:** `#architecture` `#lock-in` `#cloudflare` `#object-storage` `#blueprint-substrate` `#decision-persistence` `#conflict-audit` `#adr-049`
