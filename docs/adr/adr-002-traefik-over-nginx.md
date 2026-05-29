---
id: "kubelab-adr-002-traefik-over-nginx"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-08"
owner: manu
---

# ADR-002: Traefik over Nginx Ingress Controller

**Status**: Accepted

**Date**: 2024-01-01

## Context

KubeLab runs 40+ services requiring ingress routing, TLS termination, and middleware capabilities. While k3s ships with Traefik by default, we evaluated whether to replace it with Nginx Ingress Controller, which is more widely used in enterprise environments.

## Decision

Use Traefik as the ingress controller, as a conscious choice — not just because it ships with k3s.

## Consequences

**Positive**:

- Native Let's Encrypt integration (ACME) — automated certificate issuance and renewal without cert-manager
- Built-in dashboard for real-time routing visualization and debugging
- Middleware chains (rate limiting, headers, redirects, basic auth) configurable via IngressRoute CRDs
- Docker and Kubernetes provider auto-discovery — services are exposed automatically
- Lower resource usage than Nginx Ingress + cert-manager combined

**Negative**:

- IngressRoute CRDs are Traefik-specific, not portable to other ingress controllers
- Less community content and Stack Overflow answers compared to Nginx
- Enterprise features (WAF, advanced rate limiting) require Traefik Enterprise (paid)

**Neutral**:

- Performance is comparable for KubeLab's traffic levels
- Both support WebSocket, gRPC, and TCP routing

## References

- https://doc.traefik.io/traefik/
- Troubleshooting — Traefik troubleshooting guides
