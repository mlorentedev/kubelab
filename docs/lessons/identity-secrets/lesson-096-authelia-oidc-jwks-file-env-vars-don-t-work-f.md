---
id: lesson-096-authelia-oidc-jwks-file-env-vars-don-t-work-f
type: lesson
status: active
created: "2026-03-01"
owner: manu
category: identity-secrets
tags: [kubelab, identity-secrets]
---

# Authelia OIDC JWKS: `_FILE` Env Vars Don't Work for Array-Indexed Keys

**Context**: Deploying Authelia with OIDC provider config for MinIO SSO on K3s staging. Used `identity_providers.oidc.jwks[0].key` with `AUTHELIA_IDENTITY_PROVIDERS_OIDC_JWKS_0_KEY_FILE` env var to inject the RSA PEM from a K8s Secret file mount.

**Problem**: Authelia v4.39 does NOT support `_FILE` env var injection for array-indexed config keys. The env var `AUTHELIA_IDENTITY_PROVIDERS_OIDC_JWKS_0_KEY_FILE` is logged as "not expected", and the empty `key: ''` placeholder in the YAML is treated as a symmetric key, causing fatal error: `symmetric keys are not permitted for signing`.

**Solution**: Use the deprecated but still-functional `issuer_private_key` field instead of the `jwks` array. Changed to `AUTHELIA_IDENTITY_PROVIDERS_OIDC_ISSUER_PRIVATE_KEY_FILE=/run/secrets/oidc_jwks_key`. Authelia auto-maps `issuer_private_key` to `jwks` internally with a deprecation warning (acceptable until Authelia 5.x).

**Rule**: For Authelia OIDC JWKS key injection via K8s Secrets, use `issuer_private_key` (not `jwks[0].key`) with `_FILE` env var. The `_FILE` suffix only works for flat config keys, NOT array-indexed ones. When Authelia 5.x drops `issuer_private_key`, find the new file-based mechanism for `jwks`.

---
