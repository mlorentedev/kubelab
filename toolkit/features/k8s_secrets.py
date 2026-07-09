"""K8s secret management: decrypt SOPS → apply K8s Secrets."""

from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from toolkit.config.constants import is_placeholder
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager


@dataclass
class SecretMapping:
    """Maps a K8s Secret to its source env vars."""

    name: str
    keys: dict[str, str]  # k8s_key → flattened_env_var
    literals: dict[str, str] = field(default_factory=dict)  # k8s_key → pre-rendered value
    namespace: str = "kubelab"  # target K8s namespace


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
            # SMTP password from shared infra namespace (ADR-036, SSOT-012 PR #3).
            "smtp_password": "INFRA_SMTP_PASS",
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
            "admin-user": "BASIC_AUTH_USER",
            "password": "APPS_SERVICES_OBSERVABILITY_GRAFANA_ADMIN_PASSWORD",
            "oidc-client-secret": "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_SECRET_GRAFANA",
        },
    ),
    SecretMapping(
        name="crowdsec-bouncer",
        keys={
            "api-key": "APPS_SERVICES_SECURITY_CROWDSEC_BOUNCER_API_KEY",
        },
    ),
    SecretMapping(
        name="crowdsec-bouncer-traefik",
        keys={
            "api-key": "APPS_SERVICES_SECURITY_CROWDSEC_BOUNCER_API_KEY",
        },
        namespace="kube-system",
    ),
    SecretMapping(
        name="gitea-secrets",
        keys={
            "SECRET_KEY": "APPS_SERVICES_CORE_GITEA_SECRET_KEY",
            "ADMIN_USER": "BASIC_AUTH_USER",
            "ADMIN_PASSWORD": "APPS_SERVICES_CORE_GITEA_ADMIN_PASSWORD",
            "ADMIN_EMAIL": "APPS_SERVICES_CORE_GITEA_ADMIN_EMAIL",
            "OIDC_CLIENT_SECRET": "APPS_SERVICES_CORE_GITEA_OIDC_CLIENT_SECRET",
        },
    ),
    SecretMapping(
        name="n8n-secrets",
        keys={
            # n8n moved core -> automation (#670); env var prefix follows the new path
            "N8N_ENCRYPTION_KEY": "APPS_SERVICES_AUTOMATION_N8N_ENCRYPTION_KEY",
        },
    ),
    SecretMapping(
        name="apprise-secrets",
        keys={},
        # Option B (ADR-044 / NOTIFY-001): the routing table (tag → tgram URL) is
        # rendered into kubelab.yml by _build_apprise_config() and mounted at /config
        # so APPRISE_STATEFUL_MODE=simple resolves POST /notify/kubelab by tag.
        # The raw bot_token / chat_* values stay in SOPS, read at render time.
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
        name="homepage-secrets",
        keys={
            "HOMEPAGE_VAR_CLOUDFLARE_TOKEN": "APPS_SERVICES_DASHBOARD_HOMEPAGE_CLOUDFLARE_TOKEN",
            "HOMEPAGE_VAR_GITHUB_TOKEN": "APPS_SERVICES_DASHBOARD_HOMEPAGE_GITHUB_TOKEN",
            "HOMEPAGE_VAR_UPTIMEKUMA_KEY": "APPS_SERVICES_DASHBOARD_HOMEPAGE_UPTIMEKUMA_KEY",
        },
    ),
    SecretMapping(
        name="postgres-secrets",
        keys={
            # Shared data-service (ADR-051). The server reads POSTGRES_PASSWORD;
            # POSTGRES_USER/DB are non-secret literals in the manifest. The api
            # gets INFRA_POSTGRES_PASSWORD added to api-secrets in PR-1b.
            "POSTGRES_PASSWORD": "INFRA_POSTGRES_PASSWORD",
        },
    ),
    SecretMapping(
        name="api-secrets",
        keys={
            # SMTP password from shared infra namespace (ADR-036, PR #3).
            # User/host/port/from are non-secrets in common.yaml → ConfigMap.
            "INFRA_SMTP_PASS": "INFRA_SMTP_PASS",
            "BEEHIIV_API_KEY": "APPS_PLATFORM_API_BEEHIIV_API_KEY",
            "ZOHO_CLIENT_ID": "APPS_PLATFORM_API_ZOHO_CLIENT_ID",
            "ZOHO_CLIENT_SECRET": "APPS_PLATFORM_API_ZOHO_CLIENT_SECRET",
        },
    ),
]


def _get_kubeconfig(env: str) -> str:
    """Get kubeconfig path for the given environment."""
    import os

    return os.path.expanduser(f"~/.kube/kubelab-{env}-config")


def _kubectl_base(env: str, namespace: str = "kubelab") -> list[str]:
    return ["kubectl", "--kubeconfig", _get_kubeconfig(env), "-n", namespace]


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

    # 2. Pre-deploy guard (TOOL-019 / C6): never push a placeholder value to a cluster.
    placeholder_hits = sorted(
        f"{mapping.name}.{k8s_key}"
        for mapping in SECRET_DEFINITIONS
        for k8s_key, env_var in mapping.keys.items()
        if is_placeholder(env_vars.get(env_var))
    )
    if placeholder_hits:
        logger.error(
            "Refusing to apply — placeholder value(s) still in the vault: "
            + ", ".join(placeholder_hits)
            + ". Configure them (toolkit secrets set …) before deploying."
        )
        return False

    # 3. Build dynamic secrets that need config + SOPS merging
    dynamic_literals = _build_dynamic_literals(cm)

    # 4. Apply each secret
    all_ok = True
    for mapping in SECRET_DEFINITIONS:
        extra = dynamic_literals.get(mapping.name, {})
        ok = _apply_single_secret(mapping, env_vars, extra, dry_run, env=env, namespace=mapping.namespace)
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

    apprise_cfg = _build_apprise_config(cm)
    if apprise_cfg:
        result["apprise-secrets"] = {"kubelab.yml": apprise_cfg}

    return result


def _build_apprise_config(cm: ConfigurationManager) -> str:
    """Build the Apprise routing table (tag → tgram URL) from SOPS values.

    Option B (ADR-044): Apprise owns the tag→URL map; n8n only sends a tag.
    Rendered into the apprise-secrets Secret as kubelab.yml and mounted at /config,
    so `APPRISE_STATEFUL_MODE=simple` resolves `POST /notify/kubelab` by tag:
      - tag `page` → PAGE channel (push)
      - tag `log`  → LOG channel (archive)
    Telegram bot-token URLs embed a colon, so each URL key is quoted to keep the
    YAML mapping valid.
    """
    merged = cm.get_merged_config()
    tg = merged.get("apps", {}).get("services", {}).get("automation", {}).get("apprise", {}).get("telegram", {})
    bot_token = tg.get("bot_token", "")
    chat_page = tg.get("chat_page", "")
    chat_log = tg.get("chat_log", "")

    if not bot_token or not chat_page:
        logger.warning("Apprise telegram bot_token/chat_page missing — skipping routing config")
        return ""

    # Build as a dict and yaml.safe_dump it (audit C13): a bot-token/chat id with a
    # YAML-special char must not break the routing table. Each url is a single-key
    # map {url: {tag: ...}} — the shape Apprise's `simple` mode expects.
    urls: list[dict[str, dict[str, str]]] = [{f"tgram://{bot_token}/{chat_page}": {"tag": "page"}}]
    if chat_log:
        urls.append({f"tgram://{bot_token}/{chat_log}": {"tag": "log"}})
    else:
        logger.warning("apprise chat_log not set — the 'log' tier will not deliver until it is")

    return yaml.safe_dump({"version": 1, "urls": urls}, sort_keys=False, default_flow_style=False)


def _build_users_database(cm: ConfigurationManager) -> str:
    """Build Authelia users_database.yml from config + SOPS password hashes."""
    merged = cm.get_merged_config()
    authelia = merged.get("apps", {}).get("services", {}).get("security", {}).get("authelia", {})
    users = authelia.get("users", [])
    # SSOT-014b: admin entry derives username from apps.auth.admin_username.
    admin_username = merged.get("apps", {}).get("auth", {}).get("admin_username", "")

    if not users or not isinstance(users, list):
        logger.warning("No Authelia users found in config")
        return ""

    # Build as a dict and yaml.safe_dump it (audit C13): a displayname/email/hash
    # containing a quote, colon or newline must NOT be able to break the user DB —
    # an invalid users_database.yml locks everyone out of Authelia.
    db: dict[str, dict[str, object]] = {}
    for user in users:
        username = admin_username if user.get("is_admin") else user.get("username", "")
        hash_key = f"users_{username}_password_hash"
        password_hash = authelia.get(hash_key, "")

        if not password_hash:
            logger.warning(f"  No password hash for user '{username}' (key: {hash_key})")
            continue

        db[username] = {
            "disabled": bool(user.get("disabled", False)),
            "displayname": user.get("displayname", username),
            "password": password_hash,
            "email": user.get("email", ""),
            "groups": list(user.get("groups", []) or []),
        }

    if not db:
        return ""

    return yaml.safe_dump({"users": db}, sort_keys=False, default_flow_style=False, allow_unicode=True)


def _render_secret_manifest(name: str, namespace: str, data: dict[str, str]) -> str:
    """Render an Opaque Secret as YAML with base64-encoded `data` — in-process.

    The single delivery primitive (audit C5 / Design Tension #2): building the
    manifest here and applying it via `kubectl apply -f -` (stdin) means no secret
    value is ever passed as a subprocess argument (readable in /proc/<pid>/cmdline).
    `data` + base64 is byte-equivalent to what `kubectl create secret -o yaml`
    emitted, so the applied object is unchanged. `yaml.safe_dump` owns escaping.
    """
    manifest = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": name, "namespace": namespace},
        "type": "Opaque",
        "data": {k: base64.b64encode(v.encode("utf-8")).decode("ascii") for k, v in data.items()},
    }
    return yaml.safe_dump(manifest, sort_keys=False, default_flow_style=False)


def _apply_single_secret(
    mapping: SecretMapping,
    env_vars: dict[str, str],
    extra_literals: dict[str, str],
    dry_run: bool,
    env: str = "staging",
    namespace: str = "kubelab",
) -> bool:
    """Create or update a single K8s Secret. Returns True on success."""
    ns_label = f" ({namespace})" if namespace != "kubelab" else ""
    logger.info(f"Processing secret: {mapping.name}{ns_label}")

    # Collect the desired key set from env vars + pre-rendered literals.
    data: dict[str, str] = {}
    missing: list[str] = []

    for k8s_key, env_var in mapping.keys.items():
        value = env_vars.get(env_var)
        if not value:
            missing.append(f"{k8s_key} (from {env_var})")
            continue
        data[k8s_key] = value

    for k8s_key, value in extra_literals.items():
        data[k8s_key] = value

    # Fail closed (TOOL-018 / audit C2): a Secret is applied via `kubectl apply -f -`,
    # which REPLACES the whole Secret. Applying a subset would shrink the live Secret
    # and silently drop the missing keys on the next pod restart. Never apply a
    # partial render — refuse and let apply_secrets report it.
    if missing:
        logger.error(
            f"  Refusing to apply {mapping.name}: {len(missing)} of {len(mapping.keys)} "
            f"source value(s) missing — {', '.join(missing)}. Applying a partial Secret "
            f"would drop those keys from the live Secret."
        )
        return False

    if dry_run:
        logger.info(f"  [DRY-RUN] Would apply secret '{mapping.name}' with keys: {list(data)}")
        return True

    # Render in-process (no secret in argv) and apply via stdin.
    manifest = _render_secret_manifest(mapping.name, namespace, data)
    try:
        apply_result = subprocess.run(
            [*_kubectl_base(env, namespace), "apply", "-f", "-"],
            input=manifest,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.success(f"  {apply_result.stdout.strip()}")
        return True

    except subprocess.CalledProcessError as e:
        logger.error(f"  Failed to apply {mapping.name}: {e.stderr}")
        return False
