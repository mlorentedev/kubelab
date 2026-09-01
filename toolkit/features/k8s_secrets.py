"""K8s secret management: decrypt SOPS → apply K8s Secrets."""

from __future__ import annotations

import base64
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from toolkit.config.constants import is_placeholder
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager, resolve_user_identity
from toolkit.features.k8s_kubeconfig import output_path


@dataclass
class SecretMapping:
    """Maps a K8s Secret to its source env vars."""

    name: str
    keys: dict[str, str]  # k8s_key → flattened_env_var
    optional_keys: dict[str, str] = field(default_factory=dict)  # k8s_key → flattened_env_var (optional)
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
            # `admin-user` is NOT here: it is an identity, not a credential, and
            # arrives as a literal resolved from apps.auth.identities.superadmin
            # (AUTH-004 C1). It used to map to BASIC_AUTH_USER — see the comment
            # in _build_dynamic_literals for what that alias cost.
            "password": "APPS_SERVICES_OBSERVABILITY_GRAFANA_ADMIN_PASSWORD",
            "oidc-client-secret": "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_SECRET_GRAFANA",
            # OBS-019: read by `toolkit obs alerts` via `kubectl get secret`,
            # never mounted into the Grafana pod itself.
            "alerts-ro-token": "APPS_SERVICES_OBSERVABILITY_GRAFANA_ALERTS_RO_TOKEN",
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
    # gitea-secrets removed: Gitea left K3s for the Beelink (ADR-061), so no
    # workload in any environment consumes this Secret. Left in place it would
    # keep pushing a dead Secret to both clusters, and — because gitea's specs
    # no longer resolve under staging — trip the placeholder guard above on
    # every `apply-secrets ENV=staging`. Its values are now rendered into the
    # Compose file by `roles/beelink_services`.
    SecretMapping(
        name="n8n-secrets",
        keys={
            # n8n moved core -> automation (#670); env var prefix follows the new path
            "N8N_ENCRYPTION_KEY": "APPS_SERVICES_AUTOMATION_N8N_ENCRYPTION_KEY",
        },
        optional_keys={
            "VIKUNJA_API_TOKEN": "APPS_SERVICES_AUTOMATION_N8N_VIKUNJA_API_TOKEN",
            "FORGE_WEBHOOK_SECRET": "APPS_SERVICES_AUTOMATION_N8N_FORGE_WEBHOOK_SECRET",
            "SLACK_SIGNING_SECRET": "APPS_SERVICES_AUTOMATION_N8N_SLACK_SIGNING_SECRET",
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
            # `MINIO_ROOT_USER` is NOT here: it was a SECOND copy of the admin
            # identity stored in SOPS, and one identity stored twice drifts —
            # #1355 facet 3 records exactly that happening. It now arrives as a
            # literal resolved from apps.auth.identities.superadmin.
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
    SecretMapping(
        name="vikunja-secrets",
        keys={
            "VIKUNJA_DATABASE_PASSWORD": "APPS_SERVICES_CORE_VIKUNJA_DB_PASSWORD",
            # Provider-scoped key (matches NAME/AUTHURL/CLIENTID on the "authelia"
            # provider in vikunja-config) -- Vikunja's OIDC provider config is
            # per-provider, there is no top-level VIKUNJA_AUTH_OPENID_CLIENTSECRET.
            "VIKUNJA_AUTH_OPENID_PROVIDERS_AUTHELIA_CLIENTSECRET": (
                "APPS_SERVICES_SECURITY_AUTHELIA_OIDC_CLIENT_SECRET_VIKUNJA"
            ),
            "VIKUNJA_SERVICE_JWTSECRET": "APPS_SERVICES_CORE_VIKUNJA_JWT_SECRET",
        },
        optional_keys={
            # Catalog key paths are apps.services.core.vikunja.r2_{access,secret}_key
            # (R2, not S3 -- the env var *names* below are VIKUNJA_FILES_S3_* because
            # that's Vikunja's own config schema for its S3-compatible client).
            "VIKUNJA_FILES_S3_ACCESSKEYID": "APPS_SERVICES_CORE_VIKUNJA_R2_ACCESS_KEY",
            "VIKUNJA_FILES_S3_SECRETACCESSKEY": "APPS_SERVICES_CORE_VIKUNJA_R2_SECRET_KEY",
        },
    ),
]


def _get_kubeconfig(env: str) -> str:
    """Get kubeconfig path for the given environment."""
    return str(output_path(env))


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


def _resolve_superadmin(cm: ConfigurationManager) -> str:
    """The declared superadmin, from `apps.auth.identities` and nowhere else.

    Deliberately has no fallback to `apps.auth.admin_username` or to
    `basic_auth.user`. A fallback would make the map optional, and an optional
    SSOT is the state this closes: `apps.auth.identities` was declared on
    2026-08-23 and read by nothing for a day, while the alias kept resolving —
    a catalog nothing acts on (lesson-380). Returning "" makes the omission
    loud at apply time rather than silently reinstating the alias.
    """
    identities = cm.get_merged_config().get("apps", {}).get("auth", {}).get("identities", {})
    superadmin = str(identities.get("superadmin", "") or "")
    if not superadmin:
        logger.warning(
            "apps.auth.identities.superadmin is not declared — Grafana and MinIO will keep "
            "whatever admin identity the cluster already holds (ADR-062 D3)"
        )
    return superadmin


def _build_dynamic_literals(cm: ConfigurationManager) -> dict[str, dict[str, str]]:
    """Build pre-rendered secret values that require config + SOPS merging.

    Returns {secret_name: {k8s_key: rendered_value}}.
    """
    result: dict[str, dict[str, str]] = {}

    # AUTH-004 C1/C6 (ADR-062 D3): every service's admin identity resolves from
    # ONE declaration, `apps.auth.identities.superadmin`. It is plaintext config
    # rather than a SOPS value, which is why it arrives as a `literal` here
    # instead of through `SecretMapping.keys`.
    #
    # What this replaces, and why it is not a tidy-up. `grafana-admin.admin-user`
    # was mapped to BASIC_AUTH_USER — the *Traefik basic-auth account* — and
    # MinIO kept a second copy of the identity in SOPS. Both are identities that
    # something else is entitled to rewrite: on 2026-08-23 a routine rotation
    # rewrote `basic_auth.user`, silently renamed the only admin of a live
    # service, and broke the repair path in the same run (#1352, lessons
    # 378/379). An identity is a declaration, not a credential.
    superadmin = _resolve_superadmin(cm)
    if superadmin:
        result["grafana-admin"] = {"admin-user": superadmin}
        result["minio-secrets"] = {"MINIO_ROOT_USER": superadmin}

    users_db = _build_users_database(cm)
    if users_db:
        result["authelia-users"] = {"users_database.yml": users_db}

    apprise_cfg = _build_apprise_config(cm)
    if apprise_cfg:
        result["apprise-secrets"] = {"kubelab.yml": apprise_cfg}

    return result


def _normalize_slack_url(url: str, channel: str | None = None) -> str:
    """Normalize a Slack webhook URL or token string to Apprise slack:// URI format."""
    clean = url.strip()
    if clean.startswith("https://hooks.slack.com/services/"):
        tokens = clean.removeprefix("https://hooks.slack.com/services/").strip("/")
        base = f"slack://{tokens}"
    elif clean.startswith("slack://"):
        base = clean
    else:
        base = f"slack://{clean}"

    if channel:
        ch = channel.lstrip("#")
        if not base.endswith(f"/#{ch}") and not base.endswith(f"/{ch}"):
            base = f"{base.rstrip('/')}/#{ch}"
    return base


def _build_apprise_config(cm: ConfigurationManager) -> str:
    """Build the Apprise routing table (tag → Slack / Telegram URLs) from SOPS values.

    Option B (ADR-044 / NOTIFY-002): Apprise owns the tag→URL map; n8n only sends a tag.
    Rendered into the apprise-secrets Secret as kubelab.yml and mounted at /config,
    so `APPRISE_STATEFUL_MODE=simple` resolves `POST /notify/kubelab` by tag:
      - tag `page`   → #alerts (critical push)
      - tag `vault`  → #vault-health (knowledge governance)
      - tag `deploy` → #deployments (Argo CD / GitOps)
      - tag `log`    → #ops-log (archive / routine maintenance)
      - tag `agent`  → #agent-fleet (AI / Hermes activities)
    """
    merged = cm.get_merged_config()
    apprise_cfg = merged.get("apps", {}).get("services", {}).get("automation", {}).get("apprise", {})
    slack = apprise_cfg.get("slack", {})
    telegram = apprise_cfg.get("telegram", {})

    urls: list[dict[str, dict[str, str]]] = []

    # 1. Slack routing (NOTIFY-002 preferred)
    if slack:
        webhook_alerts = slack.get("webhook_alerts") or slack.get("webhook_page") or slack.get("webhook_url")
        webhook_vault = slack.get("webhook_vault") or webhook_alerts
        webhook_log = slack.get("webhook_log") or webhook_alerts
        webhook_deploy = slack.get("webhook_deployments") or slack.get("webhook_deploy") or webhook_alerts
        webhook_agent = slack.get("webhook_agent") or slack.get("webhook_agent_fleet") or webhook_alerts

        if webhook_alerts:
            urls.append({_normalize_slack_url(webhook_alerts, slack.get("channel_alerts", "alerts")): {"tag": "page"}})
        if webhook_vault:
            urls.append(
                {_normalize_slack_url(webhook_vault, slack.get("channel_vault", "vault-health")): {"tag": "vault"}}
            )
        if webhook_deploy:
            urls.append(
                {
                    _normalize_slack_url(webhook_deploy, slack.get("channel_deployments", "deployments")): {
                        "tag": "deploy"
                    }
                }
            )
        if webhook_log:
            urls.append({_normalize_slack_url(webhook_log, slack.get("channel_log", "ops-log")): {"tag": "log"}})
        if webhook_agent:
            urls.append(
                {_normalize_slack_url(webhook_agent, slack.get("channel_agent", "agent-fleet")): {"tag": "agent"}}
            )

    # 2. Telegram fallback during transition
    if telegram and not urls:
        bot_token = telegram.get("bot_token", "")
        chat_page = telegram.get("chat_page", "")
        chat_log = telegram.get("chat_log", "")
        if bot_token and chat_page:
            urls.append({f"tgram://{bot_token}/{chat_page}": {"tag": "page"}})
            if chat_log:
                urls.append({f"tgram://{bot_token}/{chat_log}": {"tag": "log"}})

    if not urls:
        logger.warning("Apprise Slack/Telegram configuration missing — skipping routing config")
        return ""

    return yaml.safe_dump({"version": 1, "urls": urls}, sort_keys=False, default_flow_style=False)


def _build_users_database(cm: ConfigurationManager) -> str:
    """Build Authelia users_database.yml from config + SOPS password hashes."""
    merged = cm.get_merged_config()
    authelia = merged.get("apps", {}).get("services", {}).get("security", {}).get("authelia", {})
    users = authelia.get("users", [])

    if not users or not isinstance(users, list):
        logger.warning("No Authelia users found in config")
        return ""

    # Build as a dict and yaml.safe_dump it (audit C13): a displayname/email/hash
    # containing a quote, colon or newline must NOT be able to break the user DB —
    # an invalid users_database.yml locks everyone out of Authelia.
    db: dict[str, dict[str, object]] = {}
    for user in users:
        # AUTH-004 C1: one resolver, shared with generator_authelia. See
        # configuration.resolve_user_identity for why it is not inlined here.
        username = resolve_user_identity(user, merged)
        if not username:
            logger.warning(f"  Skipping user entry that resolves to no identity: {user!r}")
            continue
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

    for k8s_key, env_var in mapping.optional_keys.items():
        value = env_vars.get(env_var)
        if value:
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
