---
id: lesson-140-error-pages-middleware-must-not-intercept-400
type: lesson
status: active
created: "2026-03-21"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# error-pages middleware must NOT intercept 400-404

**Context:** Custom error pages service deployed on K3s with Traefik errors middleware.

**Problem:** Error-pages middleware was intercepting ALL HTTP errors including 400-404. This swallowed application-level responses: API 401 = "not authenticated" became a generic error page, API 404 = "resource not found" became a generic 404 page. Clients couldn't distinguish between "endpoint doesn't exist" and "resource not found within a valid endpoint."

**Solution:** Only intercept infrastructure errors (408, 429, 500-503). Application responses (400-404) pass through to the client. The catch-all IngressRoute handles unknown domains directly via the errors service (no middleware needed there).

**Rule:** Error-pages middleware = infrastructure errors only (408, 429, 500+). Never intercept 4xx below 408 — those are application semantics.
**Tags:** `#traefik` `#error-pages` `#middleware` `#k8s`
