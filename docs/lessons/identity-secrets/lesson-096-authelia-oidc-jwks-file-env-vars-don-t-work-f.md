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

**Update 2026-10-20 (#2377)**: the file-based mechanism for `jwks` is Authelia's template filter, already used by the dev Compose stack. K8s now sets `X_AUTHELIA_CONFIG_FILTERS=template` and reads the key with `key: {{ secret "/run/secrets/oidc_jwks_key" | mindent 10 "|" | msquote }}`, so `issuer_private_key` and its `_FILE` env var are gone and `validate-config` prints no deprecation. Two traps on the way: the template line is not YAML until Authelia renders it, so it lives in its own `oidc-jwks.yml` rather than in `configuration.yml`, which many tests load as YAML; and prod's `authelia-config` generator used `behavior: replace`, which would have dropped a new base file from prod, so it is now `merge`. Leaving out `key_id` keeps the kid Authelia derived for `issuer_private_key` (`<thumbprint>-rs256`), so clients see the same kid.

**Rule**: A `_FILE` env var only fills flat config keys. To read a file into a list element (`jwks[0].key`), use the template filter's `secret` function, in a file of its own, and omit `key_id` unless clients are meant to see a new kid.

---
