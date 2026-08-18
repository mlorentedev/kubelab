---
id: lesson-075-2026-02-26-traefik-cannot-proxy-headscale-cus
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-02-26 — Traefik Cannot Proxy Headscale: Custom HTTP Upgrade Not Supported

**Context:** Testing ts-bridge v1.3.0 `TS_CONTROL_URL` against Headscale (`vpn.kubelab.live`) behind Traefik v3.0.4.

**Problem:** tsnet v1.60.0 fetches `/key` successfully but `/machine/register` via Noise protocol fails:
```
all connection attempts failed (HTTP: 308 Permanent Redirect, HTTPS: reading response header: EOF)
```

**Root cause (corrected after 3 failed attempts):**
1. ~~HTTP/2 incompatible with Upgrade headers~~ — `maxConcurrentStreams: 0` does nothing (means "unlimited", not "disable")
2. ~~TLS ALPN forcing HTTP/1.1~~ — Confirmed HTTP/1.1 via ALPN, error persisted
3. **Real cause: Traefik strips non-WebSocket `Upgrade` headers** ([traefik#12609](https://github.com/traefik/traefik/issues/12609), OPEN). Traefik only recognizes `Upgrade: websocket`. The `Upgrade: tailscale-control-protocol` header is removed as a hop-by-hop header per RFC 7230. Headscale never receives the Noise handshake → connection fails. Headscale's own docs don't list Traefik as a supported reverse proxy.

**Fix:** TCP passthrough with SNI routing — Traefik forwards raw TCP based on SNI, Headscale handles TLS itself:
```yaml
# /opt/traefik/dynamic/app-headscale.yml
tcp:
  routers:
    headscale:
      rule: "HostSNI(`vpn.kubelab.live`)"
      entryPoints:
        - websecure
      service: headscale-tcp
      tls:
        passthrough: true
  services:
    headscale-tcp:
      loadBalancer:
        servers:
          - address: "headscale:443"
```
Headscale config changes: `listen_addr: 0.0.0.0:443` + TLS cert via certbot DNS-01 (Cloudflare).

**Rule:** Before putting a service behind Traefik HTTP reverse proxy, check if it uses custom HTTP Upgrade protocols. If yes → use TCP passthrough with SNI routing. Traefik only supports `Upgrade: websocket`, nothing else. This affects Headscale, Tailscale control servers, and any custom binary protocol over HTTP Upgrade.

---
