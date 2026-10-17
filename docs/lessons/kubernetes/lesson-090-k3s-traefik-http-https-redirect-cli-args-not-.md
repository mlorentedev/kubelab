---
id: lesson-090-k3s-traefik-http-https-redirect-cli-args-not-
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# K3s Traefik HTTP→HTTPS Redirect: CLI Args, Not Helm Values

**Context**: Adding HTTP→HTTPS redirect to the K3s Traefik via HelmChartConfig.

**Problem**: First tried `ports.web.redirectTo.port: websecure` in HelmChartConfig values — this is the documented Traefik Helm chart approach. Applied successfully but Traefik deployment showed no redirect args. The K3s-managed Traefik chart may not support this value path, or it requires a specific chart version.

**Solution**: Use `additionalArguments` in HelmChartConfig to pass CLI args directly:
```yaml
additionalArguments:
  - "--entrypoints.web.http.redirections.entryPoint.to=websecure"
  - "--entrypoints.web.http.redirections.entryPoint.scheme=https"
  - "--entrypoints.web.http.redirections.entryPoint.permanent=true"
```

**Rule**: For K3s-managed Traefik, prefer `additionalArguments` over nested Helm values for configuration that maps to CLI flags. Always verify with `kubectl get deployment traefik -n kube-system -o yaml | grep -A5 args` that the flag actually appears.

---
