---
id: lesson-175-kustomize-images-section-doesn-t-cover-custom
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, kustomize, docker, release, k8s]
---

# Kustomize images section doesn't cover custom apps automatically

**Context:** `sync_k8s_images.py` syncs third-party image tags from common.yaml to kustomization.yaml `images:` section. But custom apps (errors, api, web) have their image in the base manifest (e.g., `kubelab-errors:dev`). After releasing `errors:1.1.1`, the pod kept running `:dev` because kustomize didn't override it.

**Solution:** Add custom app images to kustomization.yaml `images:` section manually. `kubectl apply -k` doesn't trigger rollout if the resolved image hasn't changed — need `rollout restart`.

**Rule:** After releasing a custom app image, update its tag in `kustomization.yaml images:` AND force rollout. Argo CD (Phase 3) solves this with image updater.
**Tags:** `#kustomize` `#docker` `#release` `#k8s`
