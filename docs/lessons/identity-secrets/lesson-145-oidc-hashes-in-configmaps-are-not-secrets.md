---
id: lesson-145-oidc-hashes-in-configmaps-are-not-secrets
type: lesson
status: active
created: "2026-03-21"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# OIDC hashes in ConfigMaps are NOT secrets

**Context:** Reviewing whether argon2 hashes of OIDC client secrets in Authelia ConfigMap are a security concern.

**Problem:** Initial instinct was to treat the hash as sensitive. But argon2 is a one-way hash — knowing the hash doesn't reveal the plaintext client_secret.

**Solution:** Hashes stay in ConfigMap (version-controlled, diff-able). Plaintext stays in SOPS → K8s Secret. `sync_oidc_hashes.py` automates hash extraction from SOPS to ConfigMap, eliminating manual copy-paste errors.

**Rule:** Argon2/bcrypt hashes are safe in ConfigMaps — they're one-way. Only the plaintext secret needs K8s Secret + SOPS protection. Automate the sync to eliminate manual errors.
**Tags:** `#security` `#oidc` `#configmap` `#sops`
