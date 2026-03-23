"""Unified secrets management: audit, init, rotate, hash, apply.

Single entry point for ALL secret operations across environments.
Delegates to ConfigurationManager for SOPS I/O and CredentialsManager
for cryptographic primitives (Argon2, RSA, htpasswd).

Design:
  - Every secret has a canonical SOPS key path (dot-separated).
  - The SECRET_CATALOG is the authoritative registry of all secrets.
  - Operations: audit (diff across envs), init (generate missing),
    rotate (regenerate + propagate), apply (SOPS → K8s).
"""

from __future__ import annotations

import secrets as stdlib_secrets
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

from toolkit.config.constants import AUTHELIA_CONFIG, PATH_STRUCTURES
from toolkit.config.settings import PROJECT_ROOT
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager

# =============================================================================
# Secret Catalog — authoritative registry of every secret
# =============================================================================


class SecretKind(str, Enum):
    """How the secret is generated/managed."""

    RANDOM_HEX = "random_hex"  # openssl rand -hex N
    RANDOM_TOKEN = "random_token"  # secrets.token_urlsafe(N)
    PASSWORD = "password"  # User-provided, interactively
    ARGON2_HASH = "argon2_hash"  # Derived from another secret
    RSA_KEY = "rsa_key"  # RSA 4096 PEM
    OIDC_CLIENT_SECRET = "oidc_client_secret"  # Random token for OIDC
    HTPASSWD = "htpasswd"  # bcrypt hash of user:pass
    EXTERNAL = "external"  # User must provide (API tokens, etc.)
    CROWDSEC_API = "crowdsec_api"  # Generated via cscli


@dataclass(frozen=True)
class SecretSpec:
    """Specification for a single secret in the SOPS vault."""

    key_path: str  # Dot-separated SOPS path
    description: str  # Human-readable purpose
    kind: SecretKind  # Generation method
    length: int = 64  # For random secrets: byte length
    services: tuple[str, ...] = ()  # Which services consume this
    derived_from: str = ""  # For hashes: key_path of the plaintext source
    format_hint: str = ""  # Expected format (e.g. "argon2id hash", "PEM RSA key")
    rotate_note: str = ""  # What breaks or needs restarting on rotation
    envs: tuple[str, ...] = ("dev", "staging", "prod")  # Which envs need this


# -- Authelia base path shortcut --
_AUTH = "apps.services.security.authelia"

SECRET_CATALOG: list[SecretSpec] = [
    # =========================================================================
    # Basic Auth (Traefik)
    # =========================================================================
    SecretSpec(
        key_path="basic_auth.user",
        description="Username for Traefik basic auth",
        kind=SecretKind.PASSWORD,
        services=("traefik",),
        format_hint="Plain text username",
        rotate_note="Regenerate Traefik config, restart traefik",
    ),
    SecretSpec(
        key_path="basic_auth.password",
        description="Password for Traefik basic auth",
        kind=SecretKind.PASSWORD,
        services=("traefik",),
        format_hint="Plain text password",
        rotate_note="Regenerate Traefik config, restart traefik",
    ),
    SecretSpec(
        key_path="basic_auth.credentials",
        description="htpasswd bcrypt hash of user:password for Traefik",
        kind=SecretKind.HTPASSWD,
        services=("traefik",),
        derived_from="basic_auth.password",
        format_hint="user:$2y$... (htpasswd bcrypt)",
        rotate_note="Auto-derived from basic_auth.user + basic_auth.password",
    ),
    # =========================================================================
    # Authelia — Session & Storage
    # =========================================================================
    SecretSpec(
        key_path=f"{_AUTH}.session_secret",
        description="Authelia session cookie encryption key",
        kind=SecretKind.RANDOM_TOKEN,
        services=("authelia",),
        rotate_note="Invalidates all active sessions. Users must re-login.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.storage_encryption_key",
        description="Authelia SQLite storage encryption key",
        kind=SecretKind.RANDOM_TOKEN,
        services=("authelia",),
        rotate_note="DANGEROUS: existing DB becomes unreadable. Must reset Authelia data.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.jwt_secret_reset_password",
        description="JWT signing key for password reset emails",
        kind=SecretKind.RANDOM_TOKEN,
        services=("authelia",),
        rotate_note="Invalidates pending password reset links.",
    ),
    # =========================================================================
    # Authelia — User Password Hashes
    # =========================================================================
    SecretSpec(
        key_path=f"{_AUTH}.users_admin_password_hash",
        description="Argon2 hash of admin user password",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from="(interactive password prompt)",
        format_hint="$argon2id$v=19$m=65536,t=3,p=4$...",
        rotate_note="User must know the new password to login.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.users_testuser_password_hash",
        description="Argon2 hash of test user password (for E2E tests)",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from="(interactive password prompt)",
        format_hint="$argon2id$v=19$m=65536,t=3,p=4$...",
        rotate_note="Update E2E test config if password changes.",
        envs=("dev", "staging", "prod"),
    ),
    # =========================================================================
    # Authelia — OIDC Provider
    # =========================================================================
    SecretSpec(
        key_path=f"{_AUTH}.oidc_hmac_secret",
        description="HMAC key for signing OIDC tokens",
        kind=SecretKind.RANDOM_TOKEN,
        services=("authelia",),
        rotate_note="Invalidates all OIDC tokens. All SSO sessions end.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_jwks_private_key",
        description="RSA 4096 private key for OIDC JWT signing (JWKS)",
        kind=SecretKind.RSA_KEY,
        services=("authelia",),
        format_hint="PEM-encoded RSA private key",
        rotate_note="All OIDC clients must re-authenticate. Restart authelia.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret",
        description="General Authelia OIDC client secret (plaintext)",
        kind=SecretKind.OIDC_CLIENT_SECRET,
        services=("authelia",),
        rotate_note="Must also regenerate the corresponding hash.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_hash",
        description="Argon2 hash of general OIDC client secret",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from=f"{_AUTH}.oidc_client_secret",
        format_hint="$argon2id$v=19$...",
        rotate_note="Auto-derived from oidc_client_secret.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_grafana",
        description="Grafana OIDC client secret (plaintext)",
        kind=SecretKind.OIDC_CLIENT_SECRET,
        services=("authelia", "grafana"),
        rotate_note="Must also regenerate the grafana hash.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_grafana_hash",
        description="Argon2 hash of Grafana OIDC client secret",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from=f"{_AUTH}.oidc_client_secret_grafana",
        format_hint="$argon2id$v=19$...",
        rotate_note="Auto-derived from oidc_client_secret_grafana.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_minio_hash",
        description="Argon2 hash of MinIO OIDC client secret",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from="apps.services.data.minio.oidc_client_secret",
        format_hint="$argon2id$v=19$...",
        rotate_note="Auto-derived from minio.oidc_client_secret.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_gitea_hash",
        description="Argon2 hash of Gitea OIDC client secret",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from="apps.services.core.gitea.oidc_client_secret",
        format_hint="$argon2id$v=19$...",
        rotate_note="Auto-derived from gitea.oidc_client_secret.",
    ),
    # =========================================================================
    # Grafana
    # =========================================================================
    SecretSpec(
        key_path="apps.services.observability.grafana.admin_user",
        description="Grafana admin username",
        kind=SecretKind.PASSWORD,
        services=("grafana",),
        rotate_note="Login with new username after restart.",
    ),
    SecretSpec(
        key_path="apps.services.observability.grafana.admin_password",
        description="Grafana admin password",
        kind=SecretKind.PASSWORD,
        services=("grafana",),
        rotate_note="Login with new password after restart.",
    ),
    # =========================================================================
    # CrowdSec
    # =========================================================================
    SecretSpec(
        key_path="apps.services.security.crowdsec.bouncer_api_key",
        description="CrowdSec bouncer API key for Traefik plugin",
        kind=SecretKind.CROWDSEC_API,
        services=("crowdsec", "traefik"),
        rotate_note="Must re-register bouncer with cscli. K8s: apply-secrets + restart bouncer.",
    ),
    # =========================================================================
    # Gitea
    # =========================================================================
    SecretSpec(
        key_path="apps.services.core.gitea.secret_key",
        description="Gitea internal security key",
        kind=SecretKind.RANDOM_HEX,
        length=32,
        services=("gitea",),
        rotate_note="Restart gitea. Existing sessions invalidated.",
        envs=("dev", "staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.core.gitea.admin_password",
        description="Gitea admin account password",
        kind=SecretKind.PASSWORD,
        services=("gitea",),
        rotate_note="Change via Gitea admin UI or CLI.",
    ),
    SecretSpec(
        key_path="apps.services.core.gitea.oidc_client_secret",
        description="Gitea OIDC client secret for Authelia SSO (plaintext)",
        kind=SecretKind.OIDC_CLIENT_SECRET,
        services=("gitea", "authelia"),
        rotate_note="Must also regenerate authelia.oidc_client_secret_gitea_hash.",
    ),
    # =========================================================================
    # N8N
    # =========================================================================
    SecretSpec(
        key_path="apps.services.core.n8n.encryption_key",
        description="N8N credential encryption key",
        kind=SecretKind.RANDOM_HEX,
        length=32,
        services=("n8n",),
        rotate_note="DANGEROUS: existing saved credentials become unreadable.",
    ),
    # =========================================================================
    # MinIO
    # =========================================================================
    SecretSpec(
        key_path="apps.services.data.minio.root_user",
        description="MinIO root (admin) username",
        kind=SecretKind.PASSWORD,
        services=("minio",),
        rotate_note="Restart minio. Re-login with new credentials.",
    ),
    SecretSpec(
        key_path="apps.services.data.minio.root_password",
        description="MinIO root (admin) password",
        kind=SecretKind.PASSWORD,
        services=("minio",),
        rotate_note="Restart minio. Re-login with new credentials.",
    ),
    SecretSpec(
        key_path="apps.services.data.minio.oidc_client_secret",
        description="MinIO OIDC client secret for Authelia SSO (plaintext)",
        kind=SecretKind.OIDC_CLIENT_SECRET,
        services=("minio", "authelia"),
        rotate_note="Must also regenerate authelia.oidc_client_secret_minio_hash.",
    ),
    # =========================================================================
    # Infrastructure (external — not auto-generated, but must exist in SOPS)
    # =========================================================================
    SecretSpec(
        key_path="cloudflare.api_token",
        description="Cloudflare DNS API token (ACME certs + Terraform DNS)",
        kind=SecretKind.EXTERNAL,
        services=("traefik", "terraform"),
        rotate_note="Re-provision K3s nodes (Ansible) + re-run terraform apply. Both read from SOPS.",
    ),
    SecretSpec(
        key_path="apps.services.automation.github_runner.token",
        description="GitHub PAT for self-hosted Actions runner registration",
        kind=SecretKind.EXTERNAL,
        services=("github-runner",),
        rotate_note="Re-provision ace2 (Ansible). Token must have repo + workflow scope.",
    ),
    # =========================================================================
    # Platform API (external — user-provided credentials)
    # =========================================================================
    SecretSpec(
        key_path="apps.platform.api.email_user",
        description="SMTP username (shared: API emails + Authelia notifications)",
        kind=SecretKind.EXTERNAL,
        services=("api", "authelia"),
        rotate_note="apply-secrets for api-secrets + authelia-secrets, restart both.",
    ),
    SecretSpec(
        key_path="apps.platform.api.email_pass",
        description="SMTP app password (shared: API emails + Authelia notifications)",
        kind=SecretKind.EXTERNAL,
        services=("api", "authelia"),
        rotate_note="apply-secrets for api-secrets + authelia-secrets, restart both.",
    ),
    SecretSpec(
        key_path="apps.platform.api.email_from",
        description="SMTP sender address (From header)",
        kind=SecretKind.EXTERNAL,
        services=("api",),
        rotate_note="apply-secrets for api-secrets.",
    ),
    SecretSpec(
        key_path="apps.platform.api.beehiiv_api_key",
        description="Beehiiv newsletter API key",
        kind=SecretKind.EXTERNAL,
        services=("api",),
        rotate_note="apply-secrets for api-secrets. Regenerate in Beehiiv dashboard.",
    ),
    SecretSpec(
        key_path="apps.platform.api.beehiiv_pub_id",
        description="Beehiiv publication ID",
        kind=SecretKind.EXTERNAL,
        services=("api",),
        rotate_note="apply-secrets for api-secrets.",
    ),
    SecretSpec(
        key_path="apps.platform.api.zoho_client_id",
        description="Zoho OAuth client ID",
        kind=SecretKind.EXTERNAL,
        services=("api",),
        rotate_note="apply-secrets for api-secrets. Regenerate in Zoho API console.",
    ),
    SecretSpec(
        key_path="apps.platform.api.zoho_client_secret",
        description="Zoho OAuth client secret",
        kind=SecretKind.EXTERNAL,
        services=("api",),
        rotate_note="apply-secrets for api-secrets. Regenerate in Zoho API console.",
    ),
]

# Build lookup by key_path for quick access
_CATALOG_BY_KEY: dict[str, SecretSpec] = {s.key_path: s for s in SECRET_CATALOG}


# =============================================================================
# Audit Result
# =============================================================================


@dataclass
class AuditResult:
    """Result of auditing secrets for an environment."""

    env: str
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)


# =============================================================================
# SecretsManager — unified operations
# =============================================================================


class SecretsManager:
    """Unified secrets management for all environments."""

    def __init__(self, project_root: Path | None = None) -> None:
        self.project_root = project_root or PROJECT_ROOT

    def _cm(self, env: str) -> ConfigurationManager:
        return ConfigurationManager(env, self.project_root)

    def _credentials_manager(self) -> Any:
        """Lazy import to avoid circular deps."""
        from toolkit.features.credentials import credentials_manager

        return credentials_manager

    # ── Audit ────────────────────────────────────────────────────────────────

    def audit(self, env: str) -> AuditResult:
        """Check which secrets exist/missing in a SOPS vault for an environment.

        Merges common.enc.yaml + {env}.enc.yaml (env overrides common),
        mirroring the same merge order as ConfigurationManager.get_merged_config().
        """
        cm = self._cm(env)
        env_file = cm.secrets_path / f"{env}.enc.yaml"
        common_file = cm.secrets_path / "common.enc.yaml"

        # Merge common + env (same order as get_merged_config)
        decrypted: dict[str, Any] = {}
        if common_file.exists():
            common_secrets = cm._decrypt_sops(common_file)
            if common_secrets:
                cm._deep_update(decrypted, common_secrets)
        if env_file.exists():
            env_secrets = cm._decrypt_sops(env_file)
            if env_secrets:
                cm._deep_update(decrypted, env_secrets)

        if not decrypted:
            return AuditResult(
                env=env,
                missing=[s.key_path for s in SECRET_CATALOG if env in s.envs],
            )

        result = AuditResult(env=env)

        for spec in SECRET_CATALOG:
            if env not in spec.envs:
                continue
            value = self._resolve_key(decrypted, spec.key_path)
            if value is not None and str(value).strip():
                result.present.append(spec.key_path)
            else:
                result.missing.append(spec.key_path)

        return result

    def audit_all(self) -> list[AuditResult]:
        """Audit all environments."""
        return [self.audit(env) for env in ("dev", "staging", "prod")]

    # ── Init (generate machine secrets) ──────────────────────────────────────

    def init_machine_secrets(self, env: str, dry_run: bool = False) -> dict[str, str]:
        """Generate all machine-generable secrets (random tokens, hex keys).

        Does NOT generate:
        - Passwords (require interactive prompt)
        - Argon2 hashes (derived from passwords)
        - CrowdSec API keys (require running container)
        - External secrets (API tokens provided by user)

        Returns dict of key_path → generated value.
        """
        auto_kinds = {
            SecretKind.RANDOM_HEX,
            SecretKind.RANDOM_TOKEN,
            SecretKind.OIDC_CLIENT_SECRET,
            SecretKind.RSA_KEY,
        }

        generated: dict[str, str] = {}

        for spec in SECRET_CATALOG:
            if env not in spec.envs:
                continue
            if spec.kind not in auto_kinds:
                continue

            value = self._generate_secret(spec)
            if value:
                generated[spec.key_path] = value

        if not dry_run and generated:
            cm = self._cm(env)
            if cm.batch_update_secrets(generated):
                logger.success(f"Wrote {len(generated)} machine secrets to {env}.enc.yaml")
            else:
                logger.error(f"Failed to write secrets to {env}.enc.yaml")
                return {}

        return generated

    # ── JWKS ─────────────────────────────────────────────────────────────────

    def generate_jwks(self, env: str) -> str:
        """Generate OIDC JWKS RSA key and store in SOPS vault.

        Also saves the PEM file for reference.
        Returns the PEM key string.
        """
        cm = self._credentials_manager()
        pem_key = cm.generate_jwks_rsa_key(AUTHELIA_CONFIG.RSA_KEY_SIZE)

        # Store in SOPS
        config_cm = self._cm(env)
        key_path = f"{_AUTH}.oidc_jwks_private_key"
        if config_cm.update_secret_key(key_path, pem_key):
            logger.success(f"JWKS key stored in {env}.enc.yaml")
        else:
            logger.error(f"Failed to store JWKS key in {env}.enc.yaml")
            return ""

        # Also save PEM file for reference
        pem_path = (
            self.project_root / PATH_STRUCTURES.CONFIG_SECRETS_DIR / AUTHELIA_CONFIG.JWKS_FILE_TEMPLATE.format(env=env)
        )
        pem_path.parent.mkdir(parents=True, exist_ok=True)
        pem_path.write_text(pem_key)
        logger.info(f"PEM file saved: {pem_path}")

        return pem_key

    # ── Hash (Argon2 for OIDC client secrets) ────────────────────────────────

    def hash_oidc_secrets(self, env: str) -> dict[str, str]:
        """Generate Argon2 hashes for all OIDC client secrets.

        Reads plaintext secrets from SOPS, generates hashes, writes hashes back.
        Returns dict of hash_key_path → hash_value.
        """
        cm = self._cm(env)
        decrypted = cm._decrypt_sops(cm.secrets_path / f"{env}.enc.yaml")
        if not decrypted:
            logger.error(f"Cannot decrypt {env}.enc.yaml")
            return {}

        cred = self._credentials_manager()
        hashes: dict[str, str] = {}

        for spec in SECRET_CATALOG:
            if env not in spec.envs:
                continue
            if spec.kind != SecretKind.ARGON2_HASH:
                continue
            if not spec.derived_from or spec.derived_from.startswith("("):
                continue  # Skip interactive-derived hashes

            plaintext = self._resolve_key(decrypted, spec.derived_from)
            if not plaintext:
                # Auto-generate OIDC client secrets if missing
                if spec.kind == SecretKind.ARGON2_HASH and "oidc_client_secret" in spec.derived_from:
                    import secrets as _secrets

                    new_secret = _secrets.token_urlsafe(64)
                    if cm.update_secret_key(spec.derived_from, new_secret):
                        logger.success(f"  Auto-generated: {spec.derived_from}")
                        plaintext = new_secret
                        # Refresh decrypted data for subsequent lookups
                        decrypted = cm._decrypt_sops(cm.secrets_path / f"{env}.enc.yaml")
                    else:
                        logger.error(f"  Failed to auto-generate: {spec.derived_from}")
                        continue
                else:
                    logger.warning(f"  Source not found: {spec.derived_from} (needed for {spec.key_path})")
                    continue

            hash_value = cred.generate_argon2_hash(str(plaintext))
            hashes[spec.key_path] = hash_value
            logger.info(f"  Hashed: {spec.derived_from} → {spec.key_path}")

        if hashes:
            if cm.batch_update_secrets(hashes):
                logger.success(f"Wrote {len(hashes)} hashes to {env}.enc.yaml")
            else:
                logger.error("Failed to write hashes")
                return {}

        return hashes

    # ── Edit (open SOPS editor) ──────────────────────────────────────────────

    def get_sops_file_path(self, env: str) -> Path:
        """Get the SOPS encrypted secrets file path for an environment."""
        return self.project_root / PATH_STRUCTURES.CONFIG_SECRETS_DIR / f"{env}.enc.yaml"

    # ── Apply (SOPS → K8s) ──────────────────────────────────────────────────

    def apply_to_k8s(self, env: str, dry_run: bool = False) -> bool:
        """Apply secrets from SOPS to Kubernetes cluster.

        Delegates to k8s_secrets.apply_secrets().
        """
        if env == "dev":
            logger.info("Dev environment uses Docker Compose, not K8s")
            return True

        from toolkit.features.k8s_secrets import apply_secrets

        return apply_secrets(env, self.project_root, dry_run=dry_run)

    # ── Show (display catalog or specific secret) ────────────────────────────

    def get_catalog(self, env: str | None = None) -> list[SecretSpec]:
        """Get catalog filtered by environment."""
        if env is None:
            return list(SECRET_CATALOG)
        return [s for s in SECRET_CATALOG if env in s.envs]

    def show_secret(self, env: str, key_path: str) -> str | None:
        """Decrypt and return a single secret value."""
        cm = self._cm(env)
        decrypted = cm._decrypt_sops(cm.secrets_path / f"{env}.enc.yaml")
        if not decrypted:
            return None
        value = self._resolve_key(decrypted, key_path)
        return str(value) if value is not None else None

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_key(data: dict[str, Any], key_path: str) -> Any:
        """Traverse nested dict by dot-separated key path."""
        current: Any = data
        for key in key_path.split("."):
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return current

    def _generate_secret(self, spec: SecretSpec) -> str:
        """Generate a secret value based on its kind."""
        if spec.kind == SecretKind.RANDOM_HEX:
            return stdlib_secrets.token_hex(spec.length)
        if spec.kind == SecretKind.RANDOM_TOKEN:
            return stdlib_secrets.token_urlsafe(spec.length)
        if spec.kind == SecretKind.OIDC_CLIENT_SECRET:
            return stdlib_secrets.token_urlsafe(spec.length)
        if spec.kind == SecretKind.RSA_KEY:
            cm = self._credentials_manager()
            return cm.generate_jwks_rsa_key(AUTHELIA_CONFIG.RSA_KEY_SIZE)
        return ""


# Global instance
secrets_manager = SecretsManager()
