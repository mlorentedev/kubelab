---
id: lesson-234-2026-03-28-argocd-helm-chart-rbac-key-is-conf
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-28: ArgoCD Helm chart RBAC key is `configs.rbac`, NOT `configs.rbacConfig`

**Symptom:** RBAC policy.csv empty in argocd-rbac-cm ConfigMap despite being in Helm values. OIDC users authenticated but saw no Applications.

**Root cause:** Old key `server.rbacConfig` was migrated to `configs.rbac` in chart v5.7.0. The intermediate `configs.rbacConfig` never existed — it was a typo that Helm silently ignored.

**Fix:** `configs.rbac.policy.csv`, `configs.rbac.policy.default`, `configs.rbac.scopes`

**Always check Context7 docs before guessing Helm value paths.**
