---
id: lesson-240-2026-03-29-argocd-selfheal-reverts-manual-kub
type: lesson
status: active
created: "2026-05-01"
owner: manu
tags: [kubelab, lesson]
---

# 2026-03-29: ArgoCD selfHeal reverts manual kubectl apply instantly

**Symptom:** `kubectl apply -f ingress.yaml` says "configured" but `kubectl get` still shows old state.

**Root cause:** ArgoCD `selfHeal: true` detects drift within seconds and reverts to Git state. The `kubectl apply` succeeds momentarily but ArgoCD's reconciliation loop overrides it immediately.

**Rule:** With ArgoCD selfHeal enabled, NEVER test K8s changes via manual `kubectl apply`. Changes must go through Git → PR → merge → ArgoCD sync. For testing, either disable selfHeal temporarily or accept dry-run validation.
