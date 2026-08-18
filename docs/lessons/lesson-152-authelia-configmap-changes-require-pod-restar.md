---
id: lesson-152-authelia-configmap-changes-require-pod-restar
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, authelia, k8s, configmap, oidc]
---

# Authelia ConfigMap changes require pod restart

**Context:** Added Grafana and Gitea OIDC clients to Authelia ConfigMap. Authelia still only showed MinIO client.

**Problem:** Authelia does NOT auto-reload `configuration.yml` when the ConfigMap changes. The file on disk updates (kubelet sync) but Authelia reads config only at startup.

**Solution:** Restart Authelia after ConfigMap changes. Long-term: convert to `configMapGenerator` with hash suffix — Kustomize auto-triggers rolling update when content changes.

**Rule:** Always verify services reload config after ConfigMap updates. Most don't (Authelia, Gitea). Some do (CoreDNS with `reload` plugin). Add restart to deploy pipeline or use configMapGenerator hash suffix.
**Tags:** `#authelia` `#k8s` `#configmap` `#oidc`
