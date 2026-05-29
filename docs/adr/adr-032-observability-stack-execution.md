---
id: adr-032-observability-stack-execution
type: adr
status: active
created: "2026-05-12"
---

# ADR-032: Observability Stack — Execution Plan and Updated Decisions

## Status

Proposed (2026-05-12). Stub captured during the DASH-* dashboard bug-fix session to record open decisions before MET-001..009 implementation. Promotes to `accepted` when MET-001 lands and the open decisions below are resolved with concrete choices.

## Context

[ADR-009](adr-009-prometheus-metrics-stack.md) (2026-02-12) accepted the Prometheus + node_exporter + cAdvisor stack design. Implementation was deferred. Since then:

- Migrated to K3s on VPS prod ([ADR-015](adr-015-vps-k3s-migration-strategy.md))
- Grafana + Loki already operational on K3s (OBS-001..004 done 2026-02-22)
- DASH-001 (Homepage cockpit, 2026-03-26) exposed the gap between instant alive/dead views (Glances widgets) and historical metrics / proactive alerts
- `kube-prometheus-stack` Helm chart matured significantly (now industry default for K8s observability)
- Operational topology decided ([ADR-028](adr-028-operational-topology.md)): observability lives on VPS prod K3s, always-on
- Hub-spoke topology ([ADR-023](adr-023-hub-spoke-multicloud-gitops.md)) added aws1 as remote spoke needing metrics coverage
- Incident 2026-05-06 (aws1 OOM cascade) confirmed the need for capacity alerting before disk/memory pressure cascades

Implementation will require decisions not addressed by ADR-009.

## Open Decisions

1. **Helm packaging** — `kube-prometheus-stack` (umbrella with Prometheus operator + own Grafana) vs `prometheus-community/prometheus` + `prometheus-community/alertmanager` as separate charts reusing the existing standalone Grafana. The umbrella conflicts with the current Grafana deployment (operator wants to own Grafana). *Tentative:* separate charts, no operator.

2. **Storage and retention** — ADR-009 set 15 days. VPS prod uses K3s `local-path` provisioner. Decisions needed: PVC size (estimate from retention × scrape interval × cardinality), backup strategy (defer to Velero per ADR-023 Phase 5). *Tentative:* 20 GiB PVC, no backup until Velero ships.

3. **Alertmanager scope** — Not covered by ADR-009. Decisions: route channel (Slack via existing webhook vs email vs N8N forwarder), alert-rules location (Kustomize in Git vs ConfigMap), severity matrix. *Tentative:* rules in Git via Kustomize, Slack route reusing existing Uptime Kuma webhook for consistency.

4. **Glances coexistence vs migration** — Glances widgets in Homepage cover instant alive/dead per host (cheap, immediate). Phase A: keep both — Grafana iframes added to Homepage Infra tab as historical view, Glances tiles stay as instant view. Phase B (post-MET-008): evaluate deprecating Glances widgets if Grafana view is preferred. *Tentative:* keep both at least 1 month after MET-008 to compare value.

5. **Cross-spoke scraping** — Prometheus on VPS prod scrapes aws1 (hub spoke) via Tailscale (`100.64.0.7:9100`). Alternative: spoke-local Prometheus with federation to hub. *Tentative:* direct scrape via Tailscale (simpler, fits current hub-spoke pattern; revisit when >2 spokes or cross-region latency hurts).

6. **K8s metrics scope** — Deploy `kube-state-metrics` (yes, for pod/deployment state). cAdvisor via kubelet built-in scrape endpoint. Traefik `--metrics.prometheus` enable in HelmChartConfig (already documented in ADR-009).

7. **High availability** — Single Prometheus replica acceptable for self-hosted scale. No Thanos, no remote-write, no long-term storage. Explicitly out of scope until VPS prod proves insufficient.

## Decision

(To be filled when promoted to `accepted` — will capture resolved choices for the 7 decisions above, with the rationale per choice.)

## Consequences

(To be filled when accepted.)

## Implementation

Tactical work tracked under existing tickets in 11-tasks:

- **D3 (Metrics)**: MET-001..009 — Prometheus stack, node_exporter, cAdvisor, Traefik metrics, scrape targets, dashboards import, custom KubeLab dashboard
- **D4 (Alerting)**: ALERT-001..005 — Alertmanager routing, log-based alerts, Slack channel, runbook links, threshold alerts (disk >85%, mem >90%, pod restart loops, TLS expiry <14d)
- **D5 (SLOs)**: SLO-001..003 — post-implementation, after baseline metrics exist

Homepage UI integration (Grafana iframes in Infra tab, gradual Glances replacement) tracked separately in the DASH-* stream when the dashboard sprint absorbs it.

## References

- [ADR-009](adr-009-prometheus-metrics-stack.md) — base decision (2026-02-12)
- [ADR-023](adr-023-hub-spoke-multicloud-gitops.md) Phase 6 — governs rollout timing
- [ADR-028](adr-028-operational-topology.md) — placement on VPS prod
- 11-tasks — D3 (MET-*), D4 (ALERT-*), D5 (SLO-*)
