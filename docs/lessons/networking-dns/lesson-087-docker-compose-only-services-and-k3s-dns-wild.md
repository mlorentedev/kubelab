---
id: lesson-087-docker-compose-only-services-and-k3s-dns-wild
type: lesson
status: active
created: "2026-02-28"
owner: manu
category: networking-dns
tags: [kubelab, networking-dns]
---

# Docker-Compose-Only Services and K3s DNS Wildcard Gap

**Context**: E2E staging tests returning self-signed TLS cert errors for portainer, gitea, n8n, minio, and uptime_kuma.

**Problem**: CoreDNS Corefile has a wildcard template `*.staging.kubelab.live → 100.64.0.4` (K3s server). This routes ALL staging subdomains to K3s. But portainer, gitea, n8n, minio, and uptime_kuma only exist as Docker Compose stacks — they have no K3s Deployments or IngressRoutes. Traefik receives requests for these domains, finds no matching IngressRoute, and returns its default self-signed certificate.

**Solution**: Added `skip_in_envs=("staging",)` in expectations.py for these services. They're legitimately not on K3s staging.

**Rule**: If a DNS wildcard covers a domain but no corresponding backend exists, Traefik returns a self-signed cert. When adding a service to the config, either: (a) deploy it on K3s with an IngressRoute, or (b) mark it with `skip_in_envs` in the test registry. The DNS wildcard is correct (forward-looking), but tests must reflect what's actually deployed.

---
