---
id: lesson-235-2026-03-28-only-spot-instances-need-dynamic-i
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# 2026-03-28: Only Spot instances need dynamic IP resolve — physical nodes keep hardcoded IPs

**Symptom:** Removing uptime-kuma.yaml from Kustomize base (for dynamic IP resolve) broke prod overlay patches — `no matches for Id IngressRoute uptime-kuma.kubelab`.

**Root cause:** Overengineering. Physical nodes (RPi3, RPi4, Beelink) have stable Tailscale IPs that never change. Only Spot instances (aws1) get new IPs on recreation.

**Rule:**
- **Kustomize base**: resources with stable IPs (physical nodes). Hardcoded IPs are correct.
- **deploy-argocd**: resources with dynamic IPs (Spot). Placeholder + MagicDNS resolve at deploy time.
- **Deploy order**: `deploy-k8s` first (Kustomize), `deploy-argocd` last (overwrites EndpointSlice with resolved IP).
- Don't solve problems that don't exist. Placeholder pattern only for IPs that actually change.
