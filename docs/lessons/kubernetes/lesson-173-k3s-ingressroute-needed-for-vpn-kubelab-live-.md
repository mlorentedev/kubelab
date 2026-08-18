---
id: lesson-173-k3s-ingressroute-needed-for-vpn-kubelab-live-
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# K3s IngressRoute needed for vpn.kubelab.live after cutover

**Context:** After K3s cutover (ports 80/443), Tailscale clients got `x509: certificate is valid for traefik.default, not vpn.kubelab.live`. All nodes disconnected from mesh.

**Problem:** Docker Compose Traefik previously proxied `vpn.kubelab.live` -> Headscale:8080. After cutover, K3s Traefik had no IngressRoute for this domain. Headscale stays in Docker Compose (ADR-015 bootstrap dependency), so it needs explicit K8s routing.

**Solution:** Created `infra/k8s/overlays/prod/headscale.yaml` with Service + EndpointSlice (162.55.57.175:8080) + IngressRoute + TLSOption (headscale-http11). Also exposed Headscale port 8080 on host in Docker Compose template.

**Rule:** When migrating from Docker Compose to K3s, services that STAY in Docker Compose (Headscale, by ADR-015) need explicit K8s external service routing (Service + EndpointSlice + IngressRoute pattern).
**Tags:** `#k3s` `#headscale` `#traefik` `#ingressroute` `#migration` `#adr-015`
