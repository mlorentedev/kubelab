---
id: lesson-174-error-middleware-only-intercept-infrastructur
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, traefik, middleware, error-pages, api]
---

# Error middleware: only intercept infrastructure errors (502/503/504)

**Context:** Error-pages middleware was intercepting 408, 429, 500-503 — breaking API JSON responses on 500s and swallowing rate-limit headers on 429s.

**Solution:** Industry standard is to intercept only 502 (Bad Gateway), 503 (Service Unavailable), 504 (Gateway Timeout) — pure infrastructure failures where the backend can't respond. Application-level errors (4xx, 500) must pass through.

**Rule:** Traefik error middleware = infrastructure errors only (502/503/504). Application error handling belongs in each app.
**Tags:** `#traefik` `#middleware` `#error-pages` `#api`
