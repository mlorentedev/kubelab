---
id: lesson-195-configmap-mount-must-use-subpath-for-homepage
type: lesson
status: active
created: "2026-03-23"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes]
---

# ConfigMap mount must use subPath for Homepage

**Context**: Deploying Homepage (gethomepage.dev) on K3s with ConfigMap-based configuration.

**Problem**: Homepage needs writable `/app/config/logs/`. Mounting the entire ConfigMap as a directory makes the whole path read-only, breaking the app.

**Solution**: Use `subPath` per config file instead of mounting the full directory.

**Rule**: When an app needs to write to its config directory (logs, cache, state), mount individual ConfigMap keys via `subPath` rather than the whole directory. Trade-off: subPath mounts don't auto-update (see RELIAB-002).
