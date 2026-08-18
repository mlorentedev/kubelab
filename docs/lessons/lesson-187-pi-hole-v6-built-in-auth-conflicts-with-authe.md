---
id: lesson-187-pi-hole-v6-built-in-auth-conflicts-with-authe
type: lesson
status: active
created: "2026-03-23"
owner: manu
tags: [kubelab, lesson]
---

# Pi-hole v6 built-in auth conflicts with Authelia

**Context**: Exposing Pi-hole admin UI via Traefik IngressRoute with Authelia middleware.

**Problem**: Pi-hole v6 has built-in authentication that returns 302 to `/admin/login`. Authelia interprets Pi-hole's 302 as "unauthenticated" and redirects back to its own login. Result: infinite redirect loop.

**Solution**: Remove Authelia middleware from Pi-hole IngressRoute. Pi-hole v6 handles its own auth. Keep CrowdSec + secure-headers middlewares for bot protection. Same pattern as n8n (built-in auth, Authelia bypass).

**Rule**: Services with built-in auth (Pi-hole v6, n8n 2.x) must NOT have Authelia middleware. Check for redirect loops when adding new services behind Authelia.
