---
id: lesson-107-nginx-security-headers-lost-in-location-block
type: lesson
status: active
created: "2026-03-07"
owner: manu
tags: [kubelab, lesson]
---

# nginx Security Headers Lost in Location Blocks

**Context**: Audit of the portfolio nginx.conf found security headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) defined in the `server` block, with a separate `location` block for static assets that had its own `add_header Cache-Control`.

**Problem**: nginx does NOT inherit `add_header` directives from parent blocks when a child `location` block contains ANY `add_header` directive. The static assets location had `add_header Cache-Control "public, immutable"` — this silently dropped all three security headers from the `server` block. Static assets (CSS, JS, fonts, images) were served without security headers.

**Solution**: Duplicate all security headers in every `location` block that has its own `add_header`. Added `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy` to the static assets location alongside the `Cache-Control` header.

**Rule**: In nginx, if any `location` block needs its own `add_header`, it MUST redeclare ALL security headers from the parent `server` block. This is a well-known nginx footgun. Always verify headers per-location with `curl -I`. Consider using `include snippets/security-headers.conf` to avoid duplication in larger configs.
