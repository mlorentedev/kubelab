---
id: lesson-088-k3s-traefik-middleware-parity-dev-has-it-stag
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# K3s Traefik Middleware Parity: Dev Has It, Staging Must Too

**Context**: E2E tests discovered staging was missing `secure-headers` and `error-pages` middlewares on individual IngressRoutes.

**Problem**: Docker Compose dev stack applies `secure-headers@file` and `error-pages@file` middlewares to ALL 15+ service routes via generated dynamic config. K3s staging had zero middleware on api/web/blog IngressRoutes (only crowdsec-bouncer), and grafana/loki only had authelia. The nginx-errors Middleware CRD existed but was only referenced by the catch-all IngressRoute, not by individual service routes. No `secure-headers` Middleware CRD existed at all.

**Impact**:
- HSTS headers missing on staging → security risk
- Custom error pages not triggered on individual routes → Traefik returns plaintext 404 instead of custom HTML
- Tests correctly caught this: 15 failures on first staging run

**Solution**:
1. Created `infra/k8s/base/edge/secure-headers.yaml` — Middleware CRD replicating the dev `secure-headers@file` config
2. Added `secure-headers` + `error-pages` to ALL IngressRoutes: api, web, blog (staging overlay), grafana, loki (base), authelia (base)
3. Middleware ordering: `secure-headers → error-pages → authelia/crowdsec-bouncer → service`

**Rule**: When adding middleware to Docker Compose routes, ALWAYS verify the equivalent Middleware CRD exists and is referenced in K3s IngressRoutes. Maintain a cross-environment middleware checklist. The E2E security headers + error pages tests are the automated guard against this drift.

---
