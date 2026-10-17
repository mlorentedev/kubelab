---
id: lesson-223-hub-singleton-credentials-must-always-write-t
type: lesson
status: active
created: "2026-03-27"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Hub singleton credentials must always write to common SOPS

**Context:** credentials-generate wrote Argo CD password to staging.enc.yaml but deploy-argocd read from common.enc.yaml — password mismatch.
**Problem:** credentials-generate writes ALL secrets to the env-specific SOPS file. But hub services (Argo CD) are singletons — their credentials must be in common SOPS regardless of which env runs the generator. This caused deploy-argocd to inject the old password hash.
**Solution:** Separate hub_secrets dict in credentials.py, written to common.enc.yaml via batch_update_secrets(secret_file_path=common_sops) in a second call. Pattern: any service that's not per-environment (hub, shared infra) gets its own write to common SOPS.
**Tags:** `#sops` `#credentials` `#architecture` `#ssot`
