---
id: lesson-207-rollout-restart-is-destructive-for-stateful-s
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# rollout restart is destructive for stateful services

**Context**: `make deploy-k8s` blanket-restarts all deployments after apply.

**Problem**: Restarting Authelia drops all sessions (403 for users). Restarting any service with in-memory state causes data loss.

**Solution**: RELIAB-001 (Authelia initContainer) + RELIAB-002 (configMapGenerator) eliminate the need for blanket restarts. Apply only restarts pods whose config actually changed.

**Rule**: Never use blanket `rollout restart` in deployment scripts. Use configMapGenerator hash suffix or similar mechanisms so only affected pods restart. Stateful services need session persistence verified before any restart strategy.
