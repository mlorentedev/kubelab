---
id: lesson-142-kustomize-images-transformer-is-ssot-for-imag
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, kustomize, images, ssot, make]
---

# Kustomize images: transformer is SSOT for image versions

**Context:** Managing container image tags across base and overlay kustomization.yaml files.

**Problem:** Image tags hardcoded in base manifests diverged from common.yaml values. Manual updates across multiple files led to version drift.

**Solution:** The `images:` section in kustomization.yaml overrides any hardcoded tags in base manifests. `make sync-k8s-images` reads from common.yaml and updates kustomization.yaml `images:` entries. This is the single source of truth for image versions in K8s.

**Rule:** Never edit image tags in base manifests directly. Use `images:` transformer in kustomization.yaml, synced from common.yaml via `make sync-k8s-images`.
**Tags:** `#kustomize` `#images` `#ssot` `#make`
