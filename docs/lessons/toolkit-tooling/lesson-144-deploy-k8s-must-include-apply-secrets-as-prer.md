---
id: lesson-144-deploy-k8s-must-include-apply-secrets-as-prer
type: lesson
status: active
created: "2026-03-21"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling]
---

# deploy-k8s must include apply-secrets as prerequisite

**Context:** Running `make deploy-k8s ENV=staging` without applying secrets first.

**Problem:** Pods fail to start with `CreateContainerConfigError` because K8s Secrets don't exist. Easy to forget the separate `apply-secrets` step, especially after cluster rebuilds.

**Solution:** Integrated apply-secrets into the deploy-k8s Makefile target as a prerequisite. Full pipeline: sync-k8s-images → sync-oidc-hashes → apply-secrets → kubectl apply.

**Rule:** Deploy targets must be self-contained. If a step is always required before deployment, make it a prerequisite, not a separate manual step.
**Tags:** `#make` `#k8s` `#secrets` `#deploy`
