---
id: lesson-143-gitea-admin-auto-creation-via-poststart-lifec
type: lesson
status: active
created: "2026-03-21"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Gitea admin auto-creation via postStart lifecycle hook

**Context:** Gitea deployment on K3s needs an admin user configured on first boot.

**Problem:** Manual `gitea admin user create` after every pod restart is fragile and forgettable. Needed an idempotent, declarative approach.

**Solution:** `postStart` lifecycle hook in the Gitea deployment creates admin from K8s Secret if not exists. Same pattern as CrowdSec bouncer auto-registration. Idempotent — skips if user already exists.

**Rule:** For services needing post-boot CLI initialization, use `postStart` lifecycle hooks with idempotent commands. Pattern: check-if-exists → create-if-not. Examples: CrowdSec bouncer, Gitea admin.
**Tags:** `#k8s` `#gitea` `#lifecycle` `#pattern`
