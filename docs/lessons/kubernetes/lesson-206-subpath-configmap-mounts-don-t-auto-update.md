---
id: lesson-206-subpath-configmap-mounts-don-t-auto-update
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# subPath ConfigMap mounts don't auto-update

**Context**: Using subPath mounts for Homepage config files (see lesson #1).

**Problem**: K8s only auto-updates full-directory ConfigMap mounts. subPath mounts are frozen at pod start time. Config changes require pod restart.

**Solution**: Use `configMapGenerator` with hash suffix in Kustomize. ConfigMap name changes on content change → triggers rolling update automatically (RELIAB-002).

**Rule**: If using subPath ConfigMap mounts, always pair with `configMapGenerator` hash suffix to get automatic rollouts on config change. Otherwise config drift is invisible.
