---
id: lesson-225-external-service-credential-reconciliation-pa
type: lesson
status: active
created: "2026-03-27"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# External service credential reconciliation pattern

**Context:** Integrating Uptime Kuma into the SSOT credential system. Services with their own auth (not K8s Secrets) need API calls to update passwords.
**Problem:** credentials-generate writes new password to SOPS, but services like Uptime Kuma manage their own user DB. K8s pod restarts don't help — the service still has the old password. Need a reconciliation step that uses each service's API.
**Solution:** Added _reconcile_external_credentials() in credentials.py. Called after SOPS update. Logs in with OLD password (from existing_secrets), calls change_password(old, new). Falls back gracefully if service unreachable. Pattern is extensible — add a try/except block per service. Future: Gitea, Grafana admin APIs.
**Tags:** `#credentials` `#ssot` `#uptime-kuma` `#architecture` `#pattern`
