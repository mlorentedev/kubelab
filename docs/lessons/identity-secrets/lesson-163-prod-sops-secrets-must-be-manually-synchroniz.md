---
id: lesson-163-prod-sops-secrets-must-be-manually-synchroniz
type: lesson
status: active
created: "2026-03-22"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Prod SOPS secrets must be manually synchronized with staging

**Context:** Deploying prod overlay failed because Gitea OIDC secrets (admin_password, oidc_client_secret, oidc_client_secret_hash) were missing from prod SOPS.

**Problem:** Staging and prod use separate SOPS files (`staging.enc.yaml`, `prod.enc.yaml`). When new secrets are added to staging during development, they must be manually copied to prod SOPS. There is no automated cross-environment secret propagation.

**Solution:** Manually ran `sops edit prod.enc.yaml` and added the missing Gitea secrets (copied values from staging where appropriate). Created backlog items TOOL-001 (secret drift detection) and TOOL-002 (secret sync tool) for automation.

**Rule:** After adding any new secret to staging SOPS, immediately add a placeholder or copy to prod SOPS. Use `toolkit secrets list --env staging` vs `--env prod` to compare. Automate this with TOOL-001/TOOL-002.

**Update 2026-10-18:** TOOL-001 was archived as integrated (#2443). `make secrets-audit` checks each env against `SECRET_CATALOG` and replaces the pairwise compare. It still exits 0 on a missing catalogued key, which is #2499. TOOL-002 is #521.
**Tags:** `#sops` `#secrets` `#environments` `#operations`
