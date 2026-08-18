---
id: lesson-188-immutable-secrets-must-be-enforced-in-code-no
type: lesson
status: active
created: "2026-03-25"
owner: manu
tags: [kubelab, lesson]
---

# IMMUTABLE_SECRETS must be enforced in code, not just documented

**Context**: MEMORY.md documented `IMMUTABLE_SECRETS` (storage_encryption_key, session_secret, jwt_secret, oidc_hmac_secret) as protected. But `credentials.py` had no protection — `batch_update_secrets` blindly overwrites all keys.

**Problem**: Running `toolkit credentials generate` would overwrite storage_encryption_key with a new random value, making Authelia's SQLite DB unreadable (encrypted with old key). Session and JWT secrets would invalidate all active sessions. This was a data-loss bug hiding behind documentation.

**Solution**: Added `IMMUTABLE_SECRETS` set in `credentials.py`. New `_read_existing_secrets()` reads SOPS before generation. `_preserve_immutable()` replaces generated values with existing ones for immutable keys. First-run (empty SOPS) uses generated values.

**Rule**: Security-critical secrets that are used as encryption keys or session state MUST have code-level protection against accidental overwrite. Documentation alone is not a safeguard — enforce invariants in code.
