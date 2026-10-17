---
id: lesson-179-hub-ingress-don-t-install-traefik-on-manageme
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: edge-tls
tags: [kubelab, edge-tls]
---

# Hub ingress: don't install Traefik on management plane — proxy via prod

**Context:** aws1 has 1GB RAM. Installing Traefik + Authelia + CrowdSec would exceed capacity. Initially tried enabling Traefik on aws1 but reverted.

**Decision:** Argo CD UI proxied through VPS (prod) Traefik using the same EndpointSlice pattern as Headscale. Zero additional software on hub.

**Rule:** Management plane should be minimal. Reuse existing ingress from data plane for UI access. Document in ADR.
**Tags:** `#architecture` `#argocd` `#traefik` `#proxy`
