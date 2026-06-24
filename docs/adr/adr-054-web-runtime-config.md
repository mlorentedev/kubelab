---
id: "adr-054"
type: adr
status: proposed
owner: manu
date: "2026-06-24"
issue: "kubelab#697"   # WEB-020 epic — this is its runtime-config sub-decision (ADR-018 gate)
tags: [architecture, decision, web, runtime-config, routing, gitops, sre]
created: "2026-06-24"
---

# ADR-054: Web Environment Configuration via Same-Origin Reverse-Proxy

## Status

Proposed 2026-06-24. Sub-decision of [[WEB-020-web-repo-extraction|WEB-020]] (#697), surfaced while extracting the `web` repo. Consumes [[adr-046-gitops-delivery-promotion-strategy|ADR-046]] (immutable build-once / promote), [[adr-053-platform-product-repos|ADR-053]] (manifests centralized in kubelab), [[adr-036-shared-infra-config|ADR-036]] (shared config SSOT), [[adr-029-intelligence-layer|ADR-029]]/[[adr-048-platform-consumer-repo-boundary|ADR-048]] (Go API gateway).

## Context

`web` (mlorente.dev) is a **static** Astro site: `import.meta.env.PUBLIC_*` is **baked at build time**. ADR-046 requires an **immutable image** built once and promoted staging→prod unchanged. These collide for any value that must differ per environment — baking a per-environment value forces a separate image per environment, which **breaks the immutable-promote invariant** (the regression class that bit us in `docs/lessons.md`: "staging must run the same artifact as prod").

Splitting configuration by **variance** dissolves most of the conflict:

- **Environment-invariant** (brand identity: site title, description, social links, analytics IDs) — this is the *product's* config, owned by the `web` repo and baked at build. It was pulled from kubelab `common.yaml` only as a monorepo accident; it moves into `web`. **Not in question.**
- **Environment-variant** (the **API base URL**, future feature flags) — cannot be baked without breaking immutability. **This ADR decides how the web reaches the API per environment.**

All of the web's API calls are **client-side** (newsletter / contact / lead-magnet form POSTs); content (projects, notes) is local MDX. There is **no build-time API fetch**, so a runtime/relative mechanism is always sufficient.

## Options Considered

1. **Bake-once against the public API.** The frontend always calls `https://api.kubelab.live` (the prod API) in every environment; one invariant value, baked. Simplest and immutable, but **staging frontend hits the prod API** — staging form submissions land in prod, no blast-radius isolation. Rejected: not SRE-sound.

2. **Runtime config injection (`config.js`).** Env-agnostic image; an nginx entrypoint writes `/config.js` from a container env var at startup; the site reads `window.__APP_CONFIG__` with a build-time fallback. The per-env value lives in kubelab `common.yaml` → ConfigMap → container env (ADR-036). Immutable and env-isolated. The standard pattern when the app must call an external origin. Cost: a config-loading indirection (JS global + entrypoint) and **CORS remains** (cross-origin to `api.kubelab.live`).

3. **Same-origin relative path + reverse-proxy.** Chosen. The frontend calls **relative** `/api/...` (no host baked). The edge (Traefik, in kubelab) routes `Host(<web-host>) && PathPrefix('/api')` → the API service **per environment**. The image bakes **zero** environment knowledge; environment variance lives entirely in the routing layer, which is already the SSOT for routing.

## Decision

Adopt **Option 3 — same-origin reverse-proxy**:

1. **Frontend** calls the API via the relative base `/api` (env-invariant; the build-time fallback for the API base becomes `/api`). The ~3 client-side call sites (`subscribe`, `lead-magnet`, `contact`) use `/api/...`.
2. **Routing (kubelab, per env)** — a Traefik IngressRoute rule on each web host (`staging.…` / prod) matches `PathPrefix('/api')` at higher priority than the web catch-all and forwards to the API service. If the API does not already serve under `/api`, a `stripPrefix` middleware is added (confirm the API's path prefix at implementation time).
3. **The image is environment-agnostic** — built once, promoted staging→prod unchanged (ADR-046 satisfied).
4. **Brand config** (title, description, social, analytics) is owned and baked by the `web` repo.
5. **The public `api.kubelab.live` stays** for external/direct API consumers — unaffected. The same-origin `/api` route is an *additional* edge path, not a replacement.

## Rationale

Against the operator's criteria — enterprise / SSOT / SRE:

- **SRE — the immutable artifact carries zero environment knowledge.** No baked URL, no runtime config file: the strongest form of "build once, run anywhere." Environment variance is an *infrastructure* concern and lives in the infrastructure layer.
- **SSOT — variance lands where it already lives.** The Traefik routing config in kubelab is already the single source of truth for request routing; this adds one route rule, not a new config surface (no `config.js`, no per-env API env var to own).
- **Enterprise — CORS is eliminated.** Same-origin removes preflight, CORS headers, and an entire class of misconfiguration; API traffic flows through the same edge, unifying logs/metrics/traces.
- **Separation of concerns** — the app renders, the edge routes.

Option 2 is the correct fallback when same-origin is infeasible (multiple backends, build-time fetch, or an un-proxiable external API) — none apply here. Option 1 is rejected for lack of staging isolation.

## Consequences

### Positive

- Image is fully environment-agnostic → clean ADR-046 promotion, no rebuild per env.
- No CORS; unified edge observability for API traffic.
- No new configuration surface to own; resolves the `PUBLIC_API_URL` default drift (code `api.staging.kubelab.live` vs spec `api.kubelab.live`) by removing the baked URL entirely.

### Negative / costs

- Web and API are coupled as a **same logical origin** at the edge (a deliberate BFF-style coupling).
- Requires refactoring the client call sites to relative paths and adding a per-env Traefik route (+ `stripPrefix` if the API serves at root).
- A future *build-time* API dependency (SSG fetching from the API) would not be served by a relative path and would require revisiting (Option 2). None exists today.

### Follow-ups

- Confirm the API's path prefix (`/api/*` vs root) to decide `stripPrefix`.
- Implement: relative call sites in `web`; Traefik IngressRoute `/api` per env in kubelab `infra/k8s/overlays/*`.
- Move brand config (title/description/social/analytics) into the `web` repo as its build-time SSOT.

## References

- [[adr-046-gitops-delivery-promotion-strategy|ADR-046]] (immutable promote), [[adr-053-platform-product-repos|ADR-053]] (manifests in kubelab), [[adr-036-shared-infra-config|ADR-036]] (config SSOT), [[adr-048-platform-consumer-repo-boundary|ADR-048]] (API gateway boundary)
- Epic: WEB-020 (#697); pilot governance: GOV-001 (#749)
