---
id: lesson-597-an-immutable-cache-header-on-an-unversioned-url-makes-a-new-asset-unreachable
type: lesson
status: active
created: "2026-10-18"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls, branding, cache, adr-071]
---

# An immutable cache header on an unversioned URL makes a new asset unreachable

**Context**: IDP-048 (#2471) replaced the brand mark. The assets live in `edge/errors/html/brand/` and are served at `assets.<env>.kubelab.live/brand/` with `Cache-Control: public, max-age=31536000, immutable` (ADR-071 D3).

**Problem**: `immutable` tells a browser not to revalidate for a year. The policy is only safe when the URL changes whenever the bytes do, and nothing in the substrate makes that true: `logo.png` keeps its name. A browser that had seen the old logo would have kept it, and every consumer would have looked unchanged with no error anywhere, because the new file was deployed correctly and was simply never asked for.

**Solution**: Each consumer URL carries `?v=<date>` (the Vikunja env files). nginx ignores the query string for `location /brand/`, so the file is the same and the cache key is new. That is a convention each consumer has to remember, so the root fix is filed as #2472: the generator emits a content-hashed name and the consumers read it.

**Rule**: A far-future immutable header is a promise that the URL names the bytes. Before shipping it, check that something enforces the promise, and when changing an asset served this way, change its URL in the same commit.

**Tags**: `#cache` `#branding` `#pr-2471`
