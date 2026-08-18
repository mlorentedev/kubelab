---
id: lesson-039-headscale-v0-28-works-with-http-proxy-not-tcp
type: lesson
status: active
created: "2026-03-15"
owner: manu
tags: [kubelab, lesson]
---

# Headscale v0.28 works with HTTP proxy (not TCP passthrough)

**Context**: VPN health endpoint broken, Uptime Kuma alerting. TCP passthrough config routed to headscale:443 where nothing listened.

**Problem**: Blog note said TCP passthrough was required for Noise protocol. Testing showed HTTP proxy (Traefik terminates TLS, forwards HTTP to headscale:8080) works perfectly with v0.28. The original TCP passthrough failure was likely a port mismatch, not a protocol incompatibility.

**Solution**: Changed Traefik dynamic config from TCP passthrough to HTTP proxy. Health endpoint (`/health`), control plane, and all Tailscale clients work correctly.

**Rule**: Don't treat past workarounds as permanent truths. Re-test assumptions when debugging — the original constraint may no longer apply. Headscale v0.28 docs explicitly recommend HTTP proxy with WebSocket upgrade support.
