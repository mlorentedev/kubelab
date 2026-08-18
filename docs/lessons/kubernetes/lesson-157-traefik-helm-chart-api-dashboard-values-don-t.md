---
id: lesson-157-traefik-helm-chart-api-dashboard-values-don-t
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# Traefik Helm chart api.dashboard values don't work in K3s HelmChartConfig

**Context:** Needed to enable Traefik dashboard on K3s for debugging routes.

**Problem:** Setting `api: { dashboard: true }` in HelmChartConfig valuesContent has no effect in K3s-managed Traefik. The values are silently ignored.

**Solution:** Use `additionalArguments` instead: `--api.dashboard=true` and `--api.insecure=true`. These are passed directly to the Traefik binary and always work.

**Rule:** For K3s HelmChartConfig, prefer `additionalArguments` for Traefik feature flags over nested values. Always verify via `kubectl -n kube-system describe pod traefik-*` that args are applied.
**Tags:** `#traefik` `#k3s` `#helm` `#debugging`
