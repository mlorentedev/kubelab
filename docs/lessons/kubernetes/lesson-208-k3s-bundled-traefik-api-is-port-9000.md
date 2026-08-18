---
id: lesson-208-k3s-bundled-traefik-api-is-port-9000
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# K3s bundled Traefik API is port 9000

**Context**: Configuring Homepage Traefik widget to show route/service counts.

**Problem**: Assumed Traefik API on port 8080 (standard). K3s bundled Traefik exposes API on port 9000. Combined with cross-namespace DNS failure, required hardcoded ClusterIP.

**Solution**: Use port 9000 + ClusterIP (fragile). Better: ExternalName Service pointing to Traefik in kube-system.

**Rule**: K3s bundles its own Traefik with non-standard defaults. Always check K3s HelmChartConfig for port overrides before assuming standard Traefik config.
