---
id: lesson-151-gitea-oidc-cli-writes-to-db-but-web-process-c
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, gitea, oidc, k8s, cache]
---

# Gitea OIDC: CLI writes to DB but web process caches in memory

**Context:** Configured OIDC via `gitea admin auth add-oauth` CLI but browser still used old config.

**Problem:** Gitea CLI writes auth sources to SQLite. The running web process caches OIDC provider config in memory and does NOT watch the DB for changes. A `kubectl rollout restart` is required after any `gitea admin auth` CLI operation.

**Solution:** `configure-oidc` script includes automatic `kubectl rollout restart deploy/gitea` after configuring. Same pattern as any K8s app with config-in-DB.

**Rule:** Any CLI tool that writes to a running service's database needs a service restart to take effect. Add restart to automation scripts.
**Tags:** `#gitea` `#oidc` `#k8s` `#cache`
