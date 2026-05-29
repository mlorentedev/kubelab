---
id: "kubelab-runbook-grafana-loki"
type: runbook
status: active
tags: [runbook, kubelab]
created: "2026-02-22"
owner: manu
---

# Grafana + Loki — Observability Runbook

## Overview

Grafana + Loki + Vector run on K3s staging. Vector (DaemonSet) collects logs from all pods and ships to Loki. Grafana queries Loki.

```
All K3s pods → stdout/stderr
       │
  [Vector DaemonSet] (one per node, reads /var/log/pods/)
       │
  [Loki] (single instance, PVC storage)
       │
  [Grafana] (UI, provisioned datasource)
```

## Access

- **URL**: `https://grafana.staging.kubelab.live`
- **User**: `admin`
- **Password**: stored in K8s Secret `grafana-admin`

```bash
# Retrieve password
ssh k3s-server "sudo kubectl get secret -n kubelab grafana-admin -o jsonpath='{.data.password}' | base64 -d"
```

## LogQL Quick Reference

LogQL is Loki's query language. Two types: **log queries** (return log lines) and **metric queries** (return numbers from logs).

### Basics — Label Matchers

```logql
# All logs from kubelab namespace
{namespace="kubelab"}

# Specific pod (exact match)
{pod="api-59694c6749-6gmdp"}

# Pod by prefix (regex)
{pod=~"api.*"}

# Multiple labels
{namespace="kubelab", container="api"}

# Exclude a container
{namespace="kubelab", container!="vector"}
```

**Label operators:** `=` exact, `!=` not equal, `=~` regex, `!~` not regex

### Filtering — Pipeline Stages

After the label matcher, pipe `|` to filter:

```logql
# Contains text (case sensitive)
{pod=~"api.*"} |= "error"

# Does NOT contain
{pod=~"api.*"} != "/health"

# Regex filter
{pod=~"api.*"} |~ "status=(4|5)\\d{2}"

# Chain multiple filters
{namespace="kubelab"} |= "error" != "health" != "readiness"
```

**Filter operators:** `|=` contains, `!=` not contains, `|~` regex match, `!~` regex not match

### Useful Daily Queries

#### "What errors happened in the last hour?"

```logql
{namespace="kubelab"} |= "error" != "/health"
```

Set time range to "Last 1 hour" in Grafana.

#### "Show me API 5xx responses"

```logql
{pod=~"api.*"} |~ "status=(5\\d{2})"
```

#### "What's the blog doing?"

```logql
{pod=~"blog.*"} != "GET /health"
```

#### "Show Traefik access logs for a specific domain"

```logql
{pod=~"traefik.*"} |= "grafana.staging.kubelab.live"
```

#### "Pod crash/restart logs" (look around restart time)

```logql
{pod=~"web.*"} |= "fatal" or |= "panic" or |= "killed"
```

#### "All logs from a specific node"

```logql
{hostname="k3s-agent-2"}
```

#### "Exclude noisy health checks from everything"

```logql
{namespace="kubelab"} != "/health" != "/ready" != "/livez" != "/readyz" != "kube-probe"
```

### Metric Queries — Counting Things

```logql
# Errors per minute (rate)
rate({namespace="kubelab"} |= "error" [1m])

# Errors per minute by pod
sum by (pod) (rate({namespace="kubelab"} |= "error" [5m]))

# Total log volume per pod (bytes/sec)
sum by (pod) (bytes_rate({namespace="kubelab"} [5m]))

# Count of log lines per pod in last hour
sum by (pod) (count_over_time({namespace="kubelab"} [1h]))
```

### JSON Log Parsing

If a pod outputs structured JSON logs:

```logql
# Parse JSON and filter by field
{pod=~"api.*"} | json | status >= 500

# Extract specific field
{pod=~"api.*"} | json | line_format "{{.method}} {{.path}} {{.status}}"
```

### Time Range Tips

| Goal | Grafana setting |
|------|----------------|
| Quick check (what just happened?) | Last 15 minutes |
| Debugging an incident | Last 1 hour |
| Trend analysis | Last 6 hours |
| Daily review | Last 24 hours |

> **Performance tip:** Start with narrow time ranges. Loki scans logs sequentially — wider ranges = slower queries. Add more label matchers and filters to speed things up.

## Operational Cheatsheet

```bash
# Check all components are running
ssh k3s-server "sudo kubectl get pods -n kubelab -l app.kubernetes.io/component=observability"

# Loki health
ssh k3s-server "sudo kubectl exec -n kubelab deploy/grafana -- wget -qO- 'http://loki:3100/ready'"

# Loki labels (what's being indexed)
ssh k3s-server "sudo kubectl exec -n kubelab deploy/grafana -- wget -qO- 'http://loki:3100/loki/api/v1/labels'"

# Vector logs (is it shipping?)
ssh k3s-server "sudo kubectl logs -n kubelab daemonset/vector --tail=20"

# Grafana health
curl -s https://grafana.staging.kubelab.live/api/health
```

## Architecture (K8s manifests)

| Component | Manifest | Type |
|-----------|----------|------|
| Grafana | `infra/k8s/base/services/grafana.yaml` | Deployment + Service + PVC + ConfigMaps |
| Loki | `infra/k8s/base/services/loki.yaml` | Deployment + Service + PVC + ConfigMap |
| Vector | `infra/k8s/base/services/vector.yaml` | DaemonSet + RBAC + ConfigMap |

## Related

- [services-observability](../troubleshooting/services-observability.md) — Troubleshooting Grafana/Loki issues
- [dns-homelab](dns-homelab.md) — How staging domains resolve
- [k3s-setup](k3s-setup.md) — K3s cluster setup

## Last tested

2026-02-22: All 3 components running on K3s staging. Loki `ready`. Grafana UI accessible at `grafana.staging.kubelab.live`. Datasource provisioned via ConfigMap. Vector shipping logs from all 3 nodes. Logs visible in Grafana Explore with `{namespace="kubelab"}`.
