---
id: lesson-166-authelia-forwardauth-must-filter-authorizatio
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Authelia ForwardAuth must filter Authorization headers

**Context:** After logging into Authelia, browser kept showing basic_auth popup on subsequent requests.

**Problem:** Browser caches `Authorization: Basic` header from a previous 401 response. Traefik forwards ALL headers to Authelia ForwardAuth. Authelia tries to parse the Basic header, fails (empty password), returns 403.

**Solution:** Whitelist `authRequestHeaders` in the Authelia Middleware spec — only forward Cookie and X-Forwarded-* headers, explicitly exclude Authorization.

**Rule:** ForwardAuth middlewares should whitelist headers, not forward everything. The Authorization header is the most common source of loops.
**Tags:** `#authelia` `#traefik` `#forwardauth` `#security`
