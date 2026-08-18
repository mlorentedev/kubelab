---
id: lesson-147-portainer-removed-k8s-native-tooling-replaces
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, portainer, cleanup, k8s, operations]
---

# Portainer removed — K8s native tooling replaces it

**Context:** PROD-K3S-000f — Portainer was last Docker Compose management tool still running on VPS.

**Problem:** Portainer added attack surface, consumed resources, and duplicated functionality already covered by kubectl, k9s, and Grafana dashboards.

**Solution:** Removed from VPS Compose stack, DNS record, Traefik route. k9s for daily operations, Grafana for dashboards, Headlamp (future) for web UI.

**Rule:** Prefer native K8s tooling over third-party management UIs. Each additional UI is attack surface + maintenance burden.
**Tags:** `#portainer` `#cleanup` `#k8s` `#operations`
