---
id: lesson-123-2026-03-16-helm-migration-strategy-adr-021
type: lesson
status: active
created: "2026-05-01"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# 2026-03-16: Helm Migration Strategy (ADR-021)

**Lesson: Hybrid Helm — official charts for third-party, generic chart for custom apps**
- **Problem**: 15+ services with hardcoded K8s manifests (domains, IPs, versions). Kustomize overlays duplicate values from common.yaml. No versioning, no rollback, no changelogs.
- **Decision**: ADR-021 — Helm replaces Kustomize entirely. Two chart types:
  - Official Helm charts (Grafana, Loki, Authelia, etc.) consumed as dependencies
  - One generic `kubelab-app` chart for custom apps (api, web, errors)
- **Key insight**: Writing Helm charts for Grafana/Loki is NIH. Official charts are battle-tested. Our value-add is values.yaml configuration only.
- **Migration**: Incremental, service by service. H1 (pilotos) → H2 (third-party) → H3 (cleanup + B6)
