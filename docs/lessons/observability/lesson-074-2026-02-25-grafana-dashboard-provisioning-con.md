---
id: lesson-074-2026-02-25-grafana-dashboard-provisioning-con
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: observability
tags: [kubelab, observability]
---

# 2026-02-25 — Grafana dashboard provisioning: ConfigMaps ≠ Docker Compose volumes

**Problem:** Custom Grafana dashboards visible in K8s staging were not showing in Docker Compose dev.

**Root cause:** K8s uses ConfigMaps mounted as volumes for Grafana provisioning. Docker Compose has no equivalent automatic mechanism — the compose.base.yml only mounted `grafana_data:/var/lib/grafana` with zero provisioning files.

**Fix:** Create provisioning files and mount them explicitly:
```
infra/stacks/services/observability/grafana/provisioning/dashboards/provider.yaml
infra/stacks/services/observability/grafana/provisioning/datasources/loki.yaml
```
Mount in compose.base.yml:
```yaml
- ./provisioning/dashboards:/etc/grafana/provisioning/dashboards:ro
- ./provisioning/datasources:/etc/grafana/provisioning/datasources:ro
- ../../../../../infra/k8s/base/services/grafana-dashboards:/var/lib/grafana/dashboards:ro
```

**Rule:** K8s and Docker Compose use different mechanisms for config injection. When a service is deployed in both environments, provisioning files must exist for both.

---
