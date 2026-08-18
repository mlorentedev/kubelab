---
id: lesson-237-2026-03-29-argocd-staging-sync-error-after-he
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-29: ArgoCD staging sync error after Helm upgrade — stale repo-server connection

**Symptom:** Staging stuck on ComparisonError "connection refused" to repo-server IP even though repo-server is Running 1/1.

**Root cause:** Controller caches repo-server Service ClusterIP. After Helm upgrade recreates pods, the old IP is stale in the controller's connection pool.

**Fix:** `kubectl rollout restart statefulset argocd-application-controller -n argocd`. Forces new connection to repo-server.

**Prevention:** This is inherent to the full scale-down upgrade pattern. Could add controller restart as post-step in deploy-argocd Makefile target.
