---
id: lesson-238-2026-03-29-generated-ingressroutes-were-missi
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# 2026-03-29: Generated IngressRoutes were missing secure-headers middleware

**Symptom:** E2E tests for `x-frame-options`, `x-content-type-options`, and HSTS failing on api and web.

**Root cause:** `generator_k8s.py _build_middlewares()` only added `error-pages`. The `secure-headers` Middleware CRD existed in the cluster but wasn't referenced in generated IngressRoutes.

**Fix:** Added `secure-headers` as first middleware in `_build_middlewares()` — applies to ALL generated IngressRoutes.

**Rule:** When adding a Traefik middleware CRD, also update the generator that produces IngressRoutes, not just the manually-crafted ones.
