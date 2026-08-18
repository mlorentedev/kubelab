---
id: lesson-066-kustomize-configmapgenerator-for-binary-asset
type: lesson
status: active
created: "2026-02-24"
owner: manu
tags: [kubelab, lesson]
---

# Kustomize configMapGenerator for Binary Assets

**Context**: Needed to deploy custom branding assets (logo.png, favicon.ico) for Authelia's sign-in page.

**Problem**: First attempt: inline binaryData in YAML → base64 blob got corrupted during editing (13KB+ strings are fragile in YAML). Second attempt: `kubectl create configmap --from-file` → imperative, breaks IaC principle.

**Solution**: Use kustomize `configMapGenerator` with `files:` directive. Kustomize automatically handles binary files as `binaryData`. Same pattern already used for `grafana-dashboards` ConfigMap.

**Rule**: Never inline large base64 blobs in YAML. Never use imperative `kubectl create` for reproducible resources. Use `configMapGenerator` with file references — it's declarative, in Git, and handles binary encoding automatically.

---
