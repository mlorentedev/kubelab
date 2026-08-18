---
id: lesson-228-homepage-configmap-is-ad-hoc-not-in-kustomize
type: lesson
status: active
created: "2026-03-27"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# Homepage ConfigMap is ad-hoc — not in Kustomize, needs manual apply

**Context:** Dashboard not updating after sync-homepage + deploy-k8s
**Problem:** Homepage ConfigMap was created via kubectl apply (ad-hoc), not via Kustomize configMapGenerator. deploy-k8s only applies Kustomize overlays — the homepage ConfigMap content never updates. Rollout restart alone doesn't help because the ConfigMap itself has stale content.
**Solution:** sync-homepage now: (1) generates config files, (2) applies ConfigMap via kubectl create --from-file --dry-run=client | kubectl apply, (3) rollout restart. Long-term: migrate Homepage to Kustomize with configMapGenerator hash suffix.
**Tags:** `#k8s` `#configmap` `#homepage` `#kustomize`
