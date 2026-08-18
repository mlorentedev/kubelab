---
id: lesson-160-configure-oidc-py-must-use-update-oauth-not-d
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, gitea, oidc, toolkit, idempotency]
---

# configure_oidc.py must use update-oauth (not delete + add-oauth)

**Context:** Re-running OIDC configuration after changing Authelia URLs failed with an error about linked users.

**Problem:** The original script used `gitea admin auth delete` + `gitea admin auth add-oauth` to ensure idempotency. This fails when users have already linked their accounts to the OIDC auth source — Gitea refuses to delete auth sources with linked users.

**Solution:** Changed `configure_oidc.py` to use `gitea admin auth update-oauth --id <ID>` instead. The script first lists auth sources to find the existing ID, then updates in place. This preserves user linkages.

**Rule:** For any service that links external auth to local accounts (Gitea, Grafana, etc.), always use update/upsert operations for auth source configuration, never delete+recreate.
**Tags:** `#gitea` `#oidc` `#toolkit` `#idempotency`
