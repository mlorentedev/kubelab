---
id: lesson-271-static-registries-catalogs-tracking-ssot-valu
type: lesson
status: active
created: "2026-05-25"
owner: manu
tags: [kubelab, lesson, ssot, secrets, catalogs, testing, ssot-014b, codex-review]
---

# Static registries (catalogs) tracking SSOT values need explicit lockstep markers

**Context:** Master plan SSOT-014 Phase B renamed `apps.auth.admin_username` from "manu" to "operator". The SOPS hash key was renamed in lockstep: `users_manu_password_hash` → `users_operator_password_hash`. Runtime read (`k8s_secrets._build_users_database`) resolves the resolved username via SSOT-014b's `is_admin` flag — works correctly. **Codex P1 review on PR #221 caught**: `SECRET_CATALOG` in `secrets_manager.py:121` still hardcoded `users_manu_password_hash`. `toolkit secrets audit/init/rotation` workflows would have silently targeted the dead key while runtime worked fine — admin password maintenance would have been silently ineffective.
**Problem:** A static Python registry that tracks an SSOT-derived value has no compile-time link to the SSOT — when the SSOT changes, the registry doesn't follow automatically. The grep for the rename FOUND the SOPS occurrence (`*.enc.yaml`) but not the Python catalog because the SOPS files are encrypted (not text-searchable without decrypt). Runtime tests passed because they exercise the runtime read path, NOT the catalog read path. Bug was invisible to the entire local test/drift-check loop — only catalog-consuming workflows (audit, rotation) would have surfaced it, and those weren't run in the smoke test.
**Solution:** Two patterns: (1) **For each SSOT-tracked entry in a static catalog, add an inline comment naming the SSOT and explicitly flagging the lockstep requirement** (`# Tracks apps.auth.admin_username SSOT — MUST be updated in lockstep on every rename`). This makes the dependency greppable for the next rename. (2) **Future refactor candidate**: derive the `key_path` dynamically from the SSOT at catalog-build time (`key_path=f"{_AUTH}.users_{admin_username}_password_hash"`), eliminating the manual lockstep. Tracked as future ticket. Cross-cutting lesson: **runtime tests do NOT cover catalog-consuming workflows**. If a value lives in a catalog AND is read at runtime via a different path, the smoke test alone is insufficient — explicitly exercise `audit`/`init`/`rotation` paths post-rename. Hotfix shipped in PR #222.
**Tags:** `#ssot` `#secrets` `#catalogs` `#testing` `#ssot-014b` `#codex-review`
