---
id: lesson-161-authelia-oidc-issuer-url-is-request-dependent
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, oidc, authelia, k8s, networking, debugging]
---

# Authelia OIDC issuer URL is request-dependent

**Context:** Gitea OIDC login failed with issuer mismatch after configuring with internal K8s URL.

**Problem:** Authelia returns the OIDC issuer based on the request URL. If you configure Gitea with the internal cluster URL (`http://authelia.kubelab.svc:9091`), the discovered issuer is internal. But the browser OIDC redirect goes through the external URL (`https://auth.kubelab.live`), which returns a different issuer. Token validation fails because issuers don't match.

**Solution:** Always configure OIDC clients with the EXTERNAL Authelia URL for OpenID Connect discovery. The browser handles all OIDC flows, so the discovery URL must be reachable and consistent from the browser's perspective.

**Rule:** OIDC discovery URLs must always be the external/public URL, even for services running in the same cluster. Internal URLs are only for direct API calls (health checks, token introspection).
**Tags:** `#oidc` `#authelia` `#k8s` `#networking` `#debugging`
