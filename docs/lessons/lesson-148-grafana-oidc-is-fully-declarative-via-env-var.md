---
id: lesson-148-grafana-oidc-is-fully-declarative-via-env-var
type: lesson
status: active
created: "2026-03-21"
owner: manu
tags: [kubelab, lesson, grafana, oidc, declarative, pattern]
---

# Grafana OIDC is fully declarative via env vars

**Context:** Configuring Grafana as OIDC client for Authelia SSO.

**Problem:** Expected Grafana OIDC to require API calls or config file editing (like Gitea which needs CLI `gitea admin auth add-oauth`).

**Solution:** Grafana OIDC is entirely configurable via `GF_AUTH_GENERIC_OAUTH_*` env vars. No API calls, no post-boot scripts. Just set env vars in the K8s deployment and restart.

**Rule:** Check if a service supports declarative config (env vars, config file) before writing imperative setup scripts. Grafana = declarative (env vars). Gitea = imperative (CLI post-boot). CrowdSec = imperative (postStart hook).
**Tags:** `#grafana` `#oidc` `#declarative` `#pattern`
