---
id: lesson-156-authelia-forwardauth-must-filter-authorizatio
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, traefik, authelia, forwardauth, security, debugging]
---

# Authelia ForwardAuth must filter Authorization headers

**Context:** After configuring Authelia ForwardAuth for n8n, users got stuck in a 403 loop.

**Problem:** Browser caches basic_auth credentials and sends `Authorization: Basic` header on every subsequent request. Authelia's ForwardAuth receives this header, tries to parse it, fails on the empty password, and returns 403. The browser then re-prompts, user enters creds, and the cycle repeats.

**Solution:** Configure ForwardAuth middleware with explicit `authRequestHeaders` whitelist: `Cookie`, `X-Forwarded-*` headers only. This strips `Authorization` headers before they reach Authelia. Without `authRequestHeaders`, Traefik forwards ALL headers.

**Rule:** ForwardAuth middlewares should ALWAYS specify `authRequestHeaders` to whitelist only the headers the auth service needs. Never forward `Authorization` headers unless the auth service explicitly handles them.
**Tags:** `#traefik` `#authelia` `#forwardauth` `#security` `#debugging`
