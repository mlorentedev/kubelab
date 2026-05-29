---
id: "kubelab-adr-009-prometheus-metrics-stack"
type: adr
status: accepted
tags: [adr, kubelab]
created: "2026-02-12"
owner: manu
---

# ADR-009: Prometheus + Node Exporter + cAdvisor for Metrics

## Status

Accepted (2026-02-12)

## Context

KubeLab already has Grafana (visualization) and Loki (log aggregation), but lacks a metrics pipeline. There is no visibility into:

1. **Host resources**: CPU, RAM, disk, network utilization per node
2. **Container resources**: Per-container CPU, RAM, I/O consumption
3. **HTTP traffic**: Request rates, latency percentiles, error rates per Traefik route
4. **Historical trends**: No time-series data to identify patterns or capacity issues

Without metrics, diagnosing performance issues requires manual `docker stats` and `htop`, with no historical context.

## Decision

Deploy the standard Prometheus metrics stack:

| Component | Role | RAM |
|-----------|------|-----|
| **Prometheus** | Metrics scraper + time-series database | ~200-300MB |
| **Node Exporter** | Host metrics (CPU, RAM, disk, network) | ~10MB |
| **cAdvisor** | Container metrics (per-container resources) | ~50MB |
| **Traefik metrics** | HTTP request metrics (enable `--metrics.prometheus`) | 0 (already running) |

Total additional RAM: ~260-360MB on Acemagic 12GB (well within budget).

### Why Prometheus (over VictoriaMetrics)

| Criterion | Prometheus | VictoriaMetrics |
|-----------|-----------|-----------------|
| RAM | ~200-300MB | ~50-150MB |
| Community | Massive, CNCF graduated | Growing, smaller |
| Documentation | Extensive | Good |
| Grafana dashboards | Hundreds available | Same (compatible) |
| PromQL | Native | Compatible + MetricsQL |
| Ecosystem | Standard (all exporters target Prometheus) | Prometheus-compatible |

VictoriaMetrics is more resource-efficient, but Prometheus is the industry standard with vastly more documentation, community dashboards, and ecosystem support. The RAM difference (~150MB) is acceptable on 12GB hardware. Boring tech wins per project Decision Hierarchy.

### Metrics sources

**Node Exporter** (per host):
- CPU usage (per core, iowait, steal)
- Memory (used, cached, buffers, available)
- Disk (usage, I/O throughput, latency)
- Network (bytes in/out, errors, connections)
- Filesystem (usage, inodes)

**cAdvisor** (per container):
- CPU usage and throttling
- Memory usage and limits
- Network I/O per container
- Disk I/O per container
- Container restart count

**Traefik** (per route):
- Request count (by method, code, service)
- Request duration histogram (p50, p95, p99)
- Active connections
- TLS certificate expiry

### Retention and storage

- Default retention: 15 days (adjustable)
- Estimated storage: ~2GB for 15 days with ~20 containers and 5 nodes
- Storage location: Docker volume on Acemagic SSD

## Consequences

1. **Prometheus** added to `infra/stacks/services/observability/prometheus/`
2. **Node Exporter** deployed on each monitored host (Acemagic, RPi 4, VPS)
3. **cAdvisor** deployed alongside Prometheus on hosts running containers
4. **Traefik** config updated: enable `--metrics.prometheus=true` entrypoint
5. **Grafana** datasource: Prometheus added alongside Loki
6. **Dashboards**: Import community dashboards (Node Exporter Full #1860, Docker/cAdvisor #893, Traefik #17346)
7. **Alerts**: Prometheus Alertmanager or Grafana alerting for threshold-based alerts

## Related

- [service-catalog](../architecture/service-catalog.md) — New services to register
- [adr-002-traefik-over-nginx](adr-002-traefik-over-nginx.md) — Traefik provides metrics endpoint
- [deployment](../troubleshooting/deployment.md) — Deployment procedures
