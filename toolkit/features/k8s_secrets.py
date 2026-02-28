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
    templates: dict[str, str] = field(default_factory=dict)  # k8s_key → template string


# ── Secret definitions (declarative) ──────────────────────────────────────────
# Format: K8s Secret name → {secret_key: FLATTENED_ENV_VAR_NAME}
# Templates use Python str.format() with the full env_vars dict.

AUTHELIA_USERS_TEMPLATE = """users:
  admin:
    disabled: false
    displayname: Administrator
    email: {APPS_SERVICES_SECURITY_AUTHELIA_USERS_0_EMAIL}
    password: "{APPS_SERVICES_SECURITY_AUTHELIA_USERS_ADMIN_PASSWORD_HASH}"
    groups:
      - admins
      - users"""

SECRET_DEFINITIONS: list[SecretMapping] = [
    SecretMapping(
        name="authelia-secrets",
        keys={
            "session_secret": "APPS_SERVICES_SECURITY_AUTHELIA_SESSION_SECRET",
            "storage_encryption_key": "APPS_SERVICES_SECURITY_AUTHELIA_STORAGE_ENCRYPTION_KEY",
            "jwt_secret": "APPS_SERVICES_SECURITY_AUTHELIA_JWT_SECRET_RESET_PASSWORD",
            "smtp_password": "APPS_PLATFORM_API_EMAIL_PASS",
        },
    ),
    SecretMapping(
        name="authelia-users",
        keys={},
        templates={"users_database.yml": AUTHELIA_USERS_TEMPLATE},
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


def _get_kubeconfig() -> str:
    """Get kubeconfig path."""
    import os

    return os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/kubelab-config"))


def _kubectl_base() -> list[str]:
    return ["kubectl", "--kubeconfig", _get_kubeconfig(), "-n", "kubelab"]


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

    # 2. Resolve user email from list (ConfigManager flattens lists)
    _resolve_user_list_vars(env_vars, cm)

    # 3. Apply each secret
    all_ok = True
    for mapping in SECRET_DEFINITIONS:
        ok = _apply_single_secret(mapping, env_vars, dry_run)
        if not ok:
            all_ok = False

    if all_ok:
        logger.success("All K8s secrets applied successfully")
    else:
        logger.error("Some secrets failed to apply")

    return all_ok


def _resolve_user_list_vars(env_vars: dict[str, str], cm: ConfigurationManager) -> None:
    """Resolve user list fields that get flattened oddly from YAML lists."""
    merged = cm.get_merged_config()
    users = merged.get("apps", {}).get("services", {}).get("security", {}).get("authelia", {}).get("users", [])
    if users and isinstance(users, list):
        user = users[0]
        env_vars["APPS_SERVICES_SECURITY_AUTHELIA_USERS_0_EMAIL"] = str(user.get("email", ""))

    # Also resolve the password hash from SOPS (nested under different key)
    password_hash = (
        merged.get("apps", {})
        .get("services", {})
        .get("security", {})
        .get("authelia", {})
        .get("users_admin_password_hash", "")
    )
    if password_hash:
        env_vars["APPS_SERVICES_SECURITY_AUTHELIA_USERS_ADMIN_PASSWORD_HASH"] = str(password_hash)


def _apply_single_secret(mapping: SecretMapping, env_vars: dict[str, str], dry_run: bool) -> bool:
    """Create or update a single K8s Secret. Returns True on success."""
    logger.info(f"Processing secret: {mapping.name}")

    # Build --from-literal args
    literals: list[str] = []
    missing: list[str] = []

    for k8s_key, env_var in mapping.keys.items():
        value = env_vars.get(env_var)
        if not value:
            missing.append(f"{k8s_key} (from {env_var})")
            continue
        literals.append(f"--from-literal={k8s_key}={value}")

    # Build --from-literal args for templates
    for k8s_key, template in mapping.templates.items():
        try:
            rendered = template.format(**env_vars)
            literals.append(f"--from-literal={k8s_key}={rendered}")
        except KeyError as e:
            missing.append(f"{k8s_key} (template var {e})")

    if missing:
        logger.warning(f"  Missing values: {', '.join(missing)}")
        if not literals:
            logger.error(f"  No values resolved for {mapping.name} — skipping")
            return False

    # kubectl create secret ... --dry-run=client -o yaml | kubectl apply -f -
    create_cmd = [
        *_kubectl_base(),
        "create",
        "secret",
        "generic",
        mapping.name,
        *literals,
        "--dry-run=client",
        "-o",
        "yaml",
    ]

    if dry_run:
        logger.info(
            f"  [DRY-RUN] Would create secret '{mapping.name}' with keys: "
            f"{[k for k in mapping.keys] + [k for k in mapping.templates]}"
        )
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
        apply_cmd = [*_kubectl_base(), "apply", "-f", "-"]
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
