---
id: lesson-239-2026-03-29-docker-tailscale-only-port-binding
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning]
---

# 2026-03-29: Docker Tailscale-only port binding breaks K8s EndpointSlice + Ansible health checks

**Symptom:** Ollama health check `Connection refused` after provisioning. K8s IngressRoute returns `Gateway Timeout`.

**Root cause:** Binding Docker ports to Tailscale IP only (`{{ tailscale_ip }}:11434:11434`) means:
1. Ansible `uri` health checks on `localhost` fail — must use Tailscale IP
2. K8s EndpointSlice with LAN IP (172.16.1.x) fails — Traefik can't reach the Docker port on LAN
3. EndpointSlice must use Tailscale IP to match Docker bind

**Fix:** Health checks use `{{ tailscale_ip }}`, EndpointSlice uses Tailscale IP (100.64.0.5), not LAN IP.

**Rule:** When binding Docker to specific IP, ALL consumers (health checks, K8s EndpointSlice, monitoring) must use that same IP.
