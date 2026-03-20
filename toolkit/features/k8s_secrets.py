"""K8s secret management: decrypt SOPS → apply K8s Secrets."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager


@dataclass
class SecretMapping:
    """Maps a K8s Secret to its source env vars."""

    name: str
    keys: dict[str, str]  # k8s_key → flattened_env_var
    literals: dict[str, str] = field(default_factory=dict)  # k8s_key → pre-rendered value


# ── Secret definitions (declarative) ──────────────────────────────────────────
# Format: K8s Secret name → {secret_key: FLATTENED_ENV_VAR_NAME}
# The `literals` field holds pre-rendered values (set dynamically in apply_secrets).

SECRET_DEFINITIONS: list[SecretMapping] = [
    SecretMapping(
        name="authelia-secrets",
        keys={
            "session_secret": "APPS_SERVICES_SECURITY_AUTHELIA_SESSION_SECRET",
            "storage_encryption_key": "APPS_SERVICES_SECURITY_AUTHELIA_STORAGE_ENCRYPTION_KEY",
            "jwt_secret": "APPS_SERVICES_SECURITY_AUTHELIA_JWT_SECRET_RESET_PASSWORD",
            "smtp_password": "APPS_PLATFORM_API_EMAIL_PASS",
            "oidc_hmac_secret": "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_HMAC_SECRET",
            "oidc_jwks_key": "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_JWKS_PRIVATE_KEY",
        },
    ),
    SecretMapping(
        name="authelia-users",
        keys={},
        # users_database.yml populated dynamically by _build_users_database()
    ),
    SecretMapping(
        name="grafana-admin",
        keys={
            "password": "APPS_SERVICES_OBSERVABILITY_GRAFANA_ADMIN_PASSWORD",
        },
    ),
    SecretMapping(
        name="crowdsec-bouncer",
        keys={
            "api-key": "APPS_SERVICES_SECURITY_CROWDSEC_BOUNCER_API_KEY",
        },
    ),
    SecretMapping(
        name="gitea-secrets",
        keys={
            "SECRET_KEY": "APPS_SERVICES_CORE_GITEA_SECRET_KEY",
        },
    ),
    SecretMapping(
        name="n8n-secrets",
        keys={
            "N8N_ENCRYPTION_KEY": "APPS_SERVICES_CORE_N8N_ENCRYPTION_KEY",
        },
    ),
    SecretMapping(
        name="minio-secrets",
        keys={
            "MINIO_ROOT_USER": "APPS_SERVICES_DATA_MINIO_ROOT_USER",
            "MINIO_ROOT_PASSWORD": "APPS_SERVICES_DATA_MINIO_ROOT_PASSWORD",
            "MINIO_IDENTITY_OPENID_CLIENT_SECRET": "APPS_SERVICES_DATA_MINIO_OIDC_CLIENT_SECRET",
        },
    ),
    SecretMapping(
        name="api-secrets",
        keys={
            "EMAIL_PASS": "APPS_PLATFORM_API_EMAIL_PASS",
            "EMAIL_USER": "APPS_PLATFORM_API_EMAIL_USER",
            "EMAIL_FROM": "APPS_PLATFORM_API_EMAIL_FROM",
            "BEEHIIV_API_KEY": "APPS_PLATFORM_API_BEEHIIV_API_KEY",
            "BEEHIIV_PUB_ID": "APPS_PLATFORM_API_BEEHIIV_PUB_ID",
            "ZOHO_CLIENT_ID": "APPS_PLATFORM_API_ZOHO_CLIENT_ID",
            "ZOHO_CLIENT_SECRET": "APPS_PLATFORM_API_ZOHO_CLIENT_SECRET",
        },
    ),
]


def _get_kubeconfig(env: str) -> str:
    """Get kubeconfig path for the given environment."""
    import os

    return os.path.expanduser(f"~/.kube/kubelab-{env}-config")


def _kubectl_base(env: str) -> list[str]:
    return ["kubectl", "--kubeconfig", _get_kubeconfig(env), "-n", "kubelab"]


def apply_secrets(env: str, project_root: Path, dry_run: bool = False) -> bool:
    """Decrypt SOPS and apply K8s Secrets for the given environment.

    Returns True if all secrets applied successfully.
    """
    logger.section(f"K8s Secrets — {env.upper()}")

    # 1. Load all env vars (common + env + SOPS decrypted)
    cm = ConfigurationManager(env, project_root)
    env_vars = cm.get_env_vars()

    if not env_vars:
        logger.error("No env vars loaded. Check SOPS key and config files.")
        return False

    logger.success(f"Loaded {len(env_vars)} env vars from config + SOPS")

    # 2. Build dynamic secrets that need config + SOPS merging
    dynamic_literals = _build_dynamic_literals(cm)

    # 3. Apply each secret
    all_ok = True
    for mapping in SECRET_DEFINITIONS:
        extra = dynamic_literals.get(mapping.name, {})
        ok = _apply_single_secret(mapping, env_vars, extra, dry_run, env=env)
        if not ok:
            all_ok = False

    if all_ok:
        logger.success("All K8s secrets applied successfully")
    else:
        logger.error("Some secrets failed to apply")

    return all_ok


def _build_dynamic_literals(cm: ConfigurationManager) -> dict[str, dict[str, str]]:
    """Build pre-rendered secret values that require config + SOPS merging.

    Returns {secret_name: {k8s_key: rendered_value}}.
    """
    result: dict[str, dict[str, str]] = {}

    users_db = _build_users_database(cm)
    if users_db:
        result["authelia-users"] = {"users_database.yml": users_db}

    return result


def _build_users_database(cm: ConfigurationManager) -> str:
    """Build Authelia users_database.yml from config + SOPS password hashes."""
    merged = cm.get_merged_config()
    authelia = merged.get("apps", {}).get("services", {}).get("security", {}).get("authelia", {})
    users = authelia.get("users", [])

    if not users or not isinstance(users, list):
        logger.warning("No Authelia users found in config")
        return ""

    lines = ["users:"]
    for user in users:
        username = user.get("username", "")
        hash_key = f"users_{username}_password_hash"
        password_hash = authelia.get(hash_key, "")

        if not password_hash:
            logger.warning(f"  No password hash for user '{username}' (key: {hash_key})")
            continue

        disabled = str(user.get("disabled", False)).lower()
        displayname = user.get("displayname", username)
        email = user.get("email", "")
        groups = user.get("groups", [])

        lines.append(f"  {username}:")
        lines.append(f"    disabled: {disabled}")
        lines.append(f'    displayname: "{displayname}"')
        lines.append(f"    email: {email}")
        lines.append(f'    password: "{password_hash}"')
        lines.append("    groups:")
        for group in groups:
            lines.append(f"      - {group}")

    return "\n".join(lines)


def _apply_single_secret(
    mapping: SecretMapping,
    env_vars: dict[str, str],
    extra_literals: dict[str, str],
    dry_run: bool,
    env: str = "staging",
) -> bool:
    """Create or update a single K8s Secret. Returns True on success."""
    logger.info(f"Processing secret: {mapping.name}")

    # Build --from-literal args from env var keys
    from_literals: list[str] = []
    missing: list[str] = []

    for k8s_key, env_var in mapping.keys.items():
        value = env_vars.get(env_var)
        if not value:
            missing.append(f"{k8s_key} (from {env_var})")
            continue
        from_literals.append(f"--from-literal={k8s_key}={value}")

    # Add pre-rendered literals (from dynamic builders)
    for k8s_key, value in extra_literals.items():
        from_literals.append(f"--from-literal={k8s_key}={value}")

    if missing:
        logger.warning(f"  Missing values: {', '.join(missing)}")
        if not from_literals:
            logger.error(f"  No values resolved for {mapping.name} — skipping")
            return False

    # kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -
    create_cmd = [
        *_kubectl_base(env),
        "create",
        "secret",
        "generic",
        mapping.name,
        *from_literals,
        "--dry-run=client",
        "-o",
        "yaml",
    ]

    if dry_run:
        all_keys = list(mapping.keys.keys()) + list(extra_literals.keys())
        logger.info(f"  [DRY-RUN] Would create secret '{mapping.name}' with keys: {all_keys}")
        return True

    try:
        # Generate YAML
        create_result = subprocess.run(
            create_cmd,
            capture_output=True,
            text=True,
            check=True,
        )
        # Pipe to kubectl apply
        apply_cmd = [*_kubectl_base(env), "apply", "-f", "-"]
        apply_result = subprocess.run(
            apply_cmd,
            input=create_result.stdout,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.success(f"  {apply_result.stdout.strip()}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"  Failed to apply {mapping.name}: {e.stderr}")
        return False
