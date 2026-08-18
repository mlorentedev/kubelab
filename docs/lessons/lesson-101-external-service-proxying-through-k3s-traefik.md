---
id: lesson-101-external-service-proxying-through-k3s-traefik
type: lesson
status: active
created: "2026-03-01"
owner: manu
tags: [kubelab, lesson]
---

# External Service Proxying Through K3s Traefik (Uptime Kuma)

**Context**: Uptime Kuma runs on RPi3 (standalone Docker, port 3001). Accessing `status.kubelab.live` gave ERR_CONNECTION_REFUSED because there was no reverse proxy — just a raw port on a Tailscale IP.

**Problem**: RPi3 has no Traefik/Caddy. Accessing `https://status.kubelab.live` hits port 443, but Uptime Kuma only listens on 3001. No HTTPS termination, no security headers.

**Solution**: Use K3s Traefik as the reverse proxy via the "external service" pattern:
1. Create a headless `Service` (no selector) + `EndpointSlice` pointing to RPi3's Tailscale IP (`100.64.0.6:3001`)
2. Create an `IngressRoute` for `status.staging.kubelab.live` with `secure-headers`, `error-pages`, `crowdsec-bouncer` middlewares
3. Prod overlay patches the domain to `status.kubelab.live`
4. Pattern matches existing `external/ollama.yaml` — same label `kubelab.live/location: external`

**Rule**: Bare-metal services that need HTTPS/security headers should be proxied through K3s Traefik using the Service + EndpointSlice pattern in `infra/k8s/base/external/`. No need to run a reverse proxy on every bare-metal host.

---
