---
id: secrets-reference
type: runbook
status: active
tags: [runbook, kubelab, secrets, sops]
created: "2026-03-01"
owner: manu
---

# Secrets Reference — Complete Catalog

> Companion to [sops-and-secrets](sops-and-secrets.md). This file is the authoritative reference
> for every secret in the system: what it does, which services use it, how to
> change it, and what breaks.
>
> **Canonical source of truth**: `toolkit/features/secrets_manager.py` → `SECRET_CATALOG`

## Unified Workflow

All secret operations go through the toolkit. The Makefile provides thin wrappers.

```bash
# ── Day-to-day ──
toolkit secrets edit    --env staging     # Open SOPS editor
toolkit secrets show    --env staging     # Show all decrypted secrets
toolkit secrets show apps.services.core.gitea.secret_key --env staging  # Show one

# ── Setup / rotation ──
toolkit secrets init    --env staging     # Generate machine secrets (tokens, hex, RSA)
toolkit credentials generate --env staging # Generate passwords + all derived secrets
toolkit secrets jwks    --env staging     # Generate OIDC JWKS RSA key
toolkit secrets hash    --env staging     # Hash all OIDC client secrets (Argon2)
toolkit secrets apply   --env staging     # Push SOPS → K8s cluster

# ── Audit ──
toolkit secrets audit                     # Show missing/present across ALL envs
toolkit secrets audit   --env prod        # Single environment
toolkit secrets catalog                   # List all registered secrets
toolkit secrets catalog -v                # With descriptions and rotation notes
```

### Standard rotation procedure (any environment)

```bash
# 1. Generate all machine secrets (tokens, keys)
toolkit secrets init --env <env>

# 2. Generate passwords and derived hashes (interactive)
toolkit credentials generate --env <env> --auto-update

# 3. Generate OIDC JWKS key
toolkit secrets jwks --env <env>

# 4. Hash OIDC client secrets (reads plaintext, writes Argon2 hashes)
toolkit secrets hash --env <env>

# 5. Verify completeness
toolkit secrets audit --env <env>

# 6. Propagate to running services
#    Dev:     toolkit config generate --env dev  (Docker Compose reads env vars)
#    K8s:     toolkit secrets apply --env staging
#    Deploy:  toolkit infra k8s deploy --env staging
```

## Secret Catalog

### SOPS File Structure

```
infra/config/secrets/
├── common.enc.yaml     # Cross-env (Cloudflare, DockerHub, Gmail, Hetzner, webhooks)
├── dev.enc.yaml        # Dev-specific
├── staging.enc.yaml    # Staging-specific
├── prod.enc.yaml       # Prod-specific
├── dev.oidc-jwks.pem   # OIDC signing key (dev)
├── staging.oidc-jwks.pem  # OIDC signing key (staging)
└── prod.oidc-jwks.pem  # OIDC signing key (prod)
```

**Merge order**: `common.yaml → {env}.yaml → common.enc.yaml → {env}.enc.yaml`

### 1. Basic Auth (Traefik)

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `basic_auth.user` | password | Plain text | traefik |
| `basic_auth.password` | password | Plain text | traefik |
| `basic_auth.credentials` | derived | `user:$2y$...` (htpasswd bcrypt) | traefik |

**How to change**: `toolkit credentials generate` (prompts for username/password, auto-generates hash).
**What breaks**: Must regenerate Traefik config (`toolkit config generate`), restart traefik.

### 2. Authelia — Session & Storage

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `apps.services.security.authelia.session_secret` | random_token | Base64 URL-safe | authelia |
| `apps.services.security.authelia.storage_encryption_key` | random_token | Base64 URL-safe | authelia |
| `apps.services.security.authelia.jwt_secret_reset_password` | random_token | Base64 URL-safe | authelia |

**How to change**: `toolkit secrets init --env <env>` (auto-generates).
**What breaks**:
- `session_secret`: Invalidates all active sessions. Users must re-login.
- `storage_encryption_key`: **DANGEROUS** — existing DB becomes unreadable. Must reset Authelia data.
- `jwt_secret_reset_password`: Invalidates pending password reset links.

### 3. Authelia — User Passwords

| Key | Kind | Format | Envs |
|-----|------|--------|------|
| `apps.services.security.authelia.users_admin_password_hash` | argon2_hash | `$argon2id$v=19$m=65536,t=3,p=4$...` | all |
| `apps.services.security.authelia.users_testuser_password_hash` | argon2_hash | `$argon2id$v=19$m=65536,t=3,p=4$...` | dev, staging |

**How to change**:
```bash
# Interactive prompt for admin password
toolkit credentials hash-password apps.services.security.authelia.users_admin_password_hash --env <env>
# Or use the full generate command
toolkit credentials generate --env <env>
```
**What breaks**: User must know the new password to login.

### 4. Authelia — OIDC Provider

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `...authelia.oidc_hmac_secret` | random_token | Base64 URL-safe | authelia |
| `...authelia.oidc_jwks_private_key` | rsa_key | PEM RSA 4096 | authelia |
| `...authelia.oidc_client_secret` | oidc_client_secret | Base64 URL-safe | authelia |
| `...authelia.oidc_client_secret_hash` | argon2_hash | `$argon2id$...` | authelia |
| `...authelia.oidc_client_secret_grafana` | oidc_client_secret | Base64 URL-safe | authelia, grafana |
| `...authelia.oidc_client_secret_grafana_hash` | argon2_hash | `$argon2id$...` | authelia |
| `...authelia.oidc_client_secret_minio_hash` | argon2_hash | `$argon2id$...` | authelia |

**OIDC client secret pattern** (applies to ALL OIDC clients):
1. **Plaintext** stored at service SOPS path → injected as env var to the service
2. **Argon2 hash** stored at authelia SOPS path → embedded in Authelia ConfigMap
3. Hash is acceptable in ConfigMap because argon2 is irreversible

**How to change**:
```bash
toolkit secrets init --env <env>       # Regenerates plaintext secrets
toolkit secrets hash --env <env>       # Regenerates all argon2 hashes
toolkit secrets jwks --env <env>       # Regenerates JWKS RSA key
```

**What breaks**:
- `oidc_hmac_secret`: Invalidates ALL OIDC tokens. All SSO sessions end.
- `oidc_jwks_private_key`: All OIDC clients must re-authenticate.
- Client secrets: The hash must match the plaintext. Always regenerate both together.

### 5. Grafana

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `apps.services.observability.grafana.admin_user` | password | Plain text | grafana |
| `apps.services.observability.grafana.admin_password` | password | Plain text | grafana |

**How to change**: `toolkit credentials generate --env <env>` (sets same as common password).
**What breaks**: Must re-login with new credentials after restart.

### 6. CrowdSec

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `apps.services.security.crowdsec.bouncer_api_key` | crowdsec_api | Hex string | crowdsec, traefik |

**How to change**: `toolkit credentials generate --env <env>` (rotates via cscli).
**What breaks**:
- Dev: Requires running CrowdSec container (auto-started by toolkit)
- K8s: Must re-register bouncer with `cscli bouncers add --key <key>`, then `toolkit secrets apply`

### 7. Gitea

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `apps.services.core.gitea.secret_key` | random_hex | 64-char hex | gitea |
| `apps.services.core.gitea.admin_password` | password | Plain text | gitea |

**How to change**:
```bash
toolkit secrets init --env <env>       # Regenerates secret_key
toolkit secrets edit --env <env>       # Manually set admin_password
```
**What breaks**:
- `secret_key`: Existing sessions invalidated. Restart gitea.
- `admin_password`: Change via Gitea admin UI or CLI command post-deploy.

### 8. N8N

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `apps.services.core.n8n.encryption_key` | random_hex | 64-char hex | n8n |

**How to change**: `toolkit secrets init --env <env>`.
**What breaks**: **DANGEROUS** — existing saved credentials/workflows with encrypted data become unreadable.

### 9. MinIO

| Key | Kind | Format | Services |
|-----|------|--------|----------|
| `apps.services.data.minio.root_user` | password | Plain text | minio |
| `apps.services.data.minio.root_password` | password | Plain text | minio |
| `apps.services.data.minio.oidc_client_secret` | oidc_client_secret | Base64 URL-safe | minio, authelia |

**How to change**:
```bash
toolkit credentials generate --env <env>   # Sets root_user/password + OIDC secret
toolkit secrets hash --env <env>           # Regenerates Argon2 hash for Authelia
```
**What breaks**:
- Restart minio, re-login with new credentials
- OIDC secret must match the hash in Authelia config

### 10. Infrastructure (common.enc.yaml)

These live in `common.enc.yaml` and are shared across ALL environments:

| Key | Kind | Services |
|-----|------|----------|
| `cloudflare.api_token` | external | Terraform DNS |
| `dockerhub.username` | external | CI/CD image push |
| `dockerhub.token` | external | CI/CD image push |
| `hetzner.api_token` | external | VPS management |
| `apps.platform.api.email.user` | external | Gmail SMTP |
| `apps.platform.api.email.pass` | external | Gmail app password |
| `apps.platform.api.email.from` | external | Gmail sender |
| `apps.platform.api.beehiiv.*` | external | Newsletter API |
| `apps.platform.api.zoho.*` | external | CRM API |
| `webhooks.*` | external | Notification webhooks |

**How to change**: `toolkit secrets edit` (common.enc.yaml is manually edited, not auto-generated).

## K8s Secret Mappings

The bridge between SOPS and Kubernetes. Defined in `toolkit/features/k8s_secrets.py`.

| K8s Secret | Keys | Source SOPS Path |
|-----------|------|-----------------|
| `authelia-secrets` | session_secret, storage_encryption_key, jwt_secret, smtp_password, oidc_hmac_secret, oidc_jwks_key | `apps.services.security.authelia.*` |
| `authelia-users` | users_database.yml | Dynamic (built from config + hashes) |
| `grafana-admin` | password | `apps.services.observability.grafana.admin_password` |
| `crowdsec-bouncer` | api-key | `apps.services.security.crowdsec.bouncer_api_key` |
| `gitea-secrets` | SECRET_KEY | `apps.services.core.gitea.secret_key` |
| `n8n-secrets` | N8N_ENCRYPTION_KEY | `apps.services.core.n8n.encryption_key` |
| `minio-secrets` | MINIO_ROOT_USER, MINIO_ROOT_PASSWORD, MINIO_IDENTITY_OPENID_CLIENT_SECRET | `apps.services.data.minio.*` |
| `api-secrets` | EMAIL_PASS, EMAIL_USER, EMAIL_FROM, BEEHIIV_*, ZOHO_* | `apps.platform.api.*` |

## Environment Parity Checklist

Run `toolkit secrets audit` to verify. All environments should have the same secrets
(except `users_testuser_password_hash` which is dev/staging only).

## Related

- [sops-and-secrets](sops-and-secrets.md) — SOPS setup, architecture, recovery procedures
- [adr-014-secrets-management-strategy](../adr/adr-014-secrets-management-strategy.md) — Architecture decision
- [adr-016-oidc-centralized-auth](../adr/adr-016-oidc-centralized-auth.md) — OIDC auth tiers

## Last updated

2026-03-01
