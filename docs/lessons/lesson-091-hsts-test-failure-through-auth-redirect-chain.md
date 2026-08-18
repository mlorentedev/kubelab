---
id: lesson-091-hsts-test-failure-through-auth-redirect-chain
type: lesson
status: active
created: "2026-03-01"
owner: manu
tags: [kubelab, lesson]
---

# HSTS Test Failure Through Auth Redirect Chain

**Context**: E2E HSTS test passing for api/web/blog but failing for grafana/loki.

**Problem**: Grafana and Loki are behind Authelia ForwardAuth. Unauthenticated requests get 302 redirected to `auth.staging.kubelab.live`. The E2E test uses `http_client_follow` (follows redirects) and checks headers on the **final** response — which is the Authelia login page. Authelia's IngressRoute didn't have `secure-headers` middleware, so the final response lacked HSTS.

**Solution**: Added `secure-headers` middleware to the Authelia IngressRoute. Now HSTS is present on all responses in the redirect chain.

**Rule**: When testing response headers on services behind SSO, the entire redirect chain must apply the same middleware. Either: (a) add the middleware to all IngressRoutes in the chain (including the auth service), or (b) test with `follow_redirects=False` to check only the initial response. Option (a) is more secure — users see HSTS regardless of which redirect step they're on.

---
