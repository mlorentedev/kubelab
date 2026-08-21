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

from toolkit.config.constants import AUTHELIA_CONFIG, PATH_STRUCTURES, is_placeholder
from toolkit.config.settings import PROJECT_ROOT
from toolkit.core.logging import logger
from toolkit.core.sops import age_key_env
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
    HUB_MANAGED = "hub_managed"  # Written to common.enc.yaml by `credentials generate`, never by per-env `secrets init`


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
    # Tracks `apps.auth.admin_username` SSOT (SSOT-014b). Static key here —
    # when admin_username is renamed (e.g. Phase B "manu" → "operator" on
    # 2026-05-25), this catalog entry MUST be updated in lockstep with the
    # SOPS key rename, or audit/init/rotation workflows will silently target
    # the wrong path. Future refactor: derive this `key_path` dynamically
    # from the SSOT at catalog-build time so the manual lockstep is removed.
    SecretSpec(
        key_path=f"{_AUTH}.users_operator_password_hash",
        description="Argon2 hash of admin user password (username from apps.auth.admin_username SSOT)",
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
        # Tracks its source's envs (see the Gitea block). Letting this keep
        # `staging` while the source no longer resolves there would walk straight
        # into #1057: `secrets hash --env staging` treats a missing source as a
        # cue to MINT a new client secret rather than to stop.
        envs=("dev", "prod"),
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
    # Uptime Kuma push monitors — BACKUP-044 AC9 coverage heartbeat
    # =========================================================================
    # One per node with a node-path backup. The token IS the authentication:
    # `status.kubelab.live/api/push/<token>` is publicly routed and
    # unauthenticated by design, so this value is a live credential and
    # `infra/config/uptime-kuma/monitors.json` — a file in a PUBLIC repository —
    # deliberately never carries it. `monitoring_diff.hydrate_push_tokens`
    # marries the two in memory at apply time and raises for a declared monitor
    # whose token is missing, rather than letting `uptime_kuma_api` mint a
    # random one: that would create a working-looking monitor at an address no
    # sender knows, which is a watchdog that alerts forever beside a heartbeat
    # that arrives nowhere.
    #
    # Sub-keys use `_`, the seed uses `-`. Not an inconsistency — `_get_push_tokens`
    # normalises, because a kebab sub-key flattens to an env var name containing
    # hyphens that SECRET_DEFINITIONS cannot consume.
    #
    # `envs=("prod",)` with the value living in `common.enc.yaml`: Uptime Kuma is
    # a singleton on the RPi3 serving every environment (#968), and `envs` is the
    # AUDIT dimension — which environment must HAVE this secret — not the file it
    # sits in (ANSIBLE-033).
    SecretSpec(
        key_path="apps.services.observability.uptime_kuma.push_tokens.ops_backup_node_beelink",
        description="Uptime Kuma push token for beelink's node-path backup heartbeat (on-demand)",
        kind=SecretKind.RANDOM_TOKEN,
        services=("uptime-kuma", "node-backup"),
        format_hint="opaque URL-safe token; the push endpoint's only credential",
        rotate_note=(
            "Rotate here, then `make monitoring-apply` so Kuma expects the new token, then "
            "re-run `make backup ENV=prod` so beelink sends it. Order matters: the node keeps "
            "posting the old token until it is re-provisioned, and Kuma answers 404 — which "
            "reads as a missed heartbeat and pages after the 6h window."
        ),
        envs=("prod",),
    ),
    SecretSpec(
        key_path="apps.services.observability.uptime_kuma.push_tokens.ops_backup_node_rpi3",
        description="Uptime Kuma push token for rpi3's node-path backup heartbeat (always-on)",
        kind=SecretKind.RANDOM_TOKEN,
        services=("uptime-kuma", "node-backup"),
        format_hint="opaque URL-safe token; the push endpoint's only credential",
        rotate_note=(
            "Rotate here, then `make monitoring-apply` so Kuma expects the new token, then "
            "re-run `make backup ENV=prod` so rpi3 sends it. Order matters: the node keeps "
            "posting the old token until it is re-provisioned, and Kuma answers 404 — which "
            "reads as a missed heartbeat and pages after the 6h window."
        ),
        envs=("prod",),
    ),
    SecretSpec(
        key_path="apps.services.observability.uptime_kuma.push_tokens.ops_backup_node_rpi4",
        description="Uptime Kuma push token for rpi4's node-path backup heartbeat (on-demand)",
        kind=SecretKind.RANDOM_TOKEN,
        services=("uptime-kuma", "node-backup"),
        format_hint="opaque URL-safe token; the push endpoint's only credential",
        rotate_note=(
            "Rotate here, then `make monitoring-apply` so Kuma expects the new token, then "
            "re-run `make backup ENV=prod` so rpi4 sends it. Order matters: the node keeps "
            "posting the old token until it is re-provisioned, and Kuma answers 404 — which "
            "reads as a missed heartbeat and pages after the 6h window."
        ),
        envs=("prod",),
    ),
    SecretSpec(
        key_path="apps.services.observability.uptime_kuma.push_tokens.ops_backup_node_vps",
        description="Uptime Kuma push token for vps's node-path backup heartbeat (always-on)",
        kind=SecretKind.RANDOM_TOKEN,
        services=("uptime-kuma", "node-backup"),
        format_hint="opaque URL-safe token; the push endpoint's only credential",
        rotate_note=(
            "Rotate here, then `make monitoring-apply` so Kuma expects the new token, then "
            "re-run `make backup ENV=prod` so vps sends it. Order matters: the node keeps "
            "posting the old token until it is re-provisioned, and Kuma answers 404 — which "
            "reads as a missed heartbeat and pages after the 6h window."
        ),
        envs=("prod",),
    ),
    # =========================================================================
    # CrowdSec
    # =========================================================================
    SecretSpec(
        key_path="apps.services.security.crowdsec.bouncer_api_key",
        description="CrowdSec bouncer API key for Traefik plugin",
        kind=SecretKind.CROWDSEC_API,
        services=("crowdsec", "traefik"),
        rotate_note=(
            "Must re-register bouncer with cscli. K8s: apply-secrets (updates Secret in kube-system) + restart Traefik."
        ),
    ),
    # =========================================================================
    # Gitea  (singleton — ADR-061)
    # =========================================================================
    # `staging` deliberately absent from every spec below. Gitea is classified
    # `state_promotion: singleton`, so the staging twin is retired and nothing
    # resolves these keys under that env any more. The Beelink deployment does
    # NOT change that even though its playbook provisions the node with
    # `deploy_env: staging`: `provision-bee.yml` declares
    # `gitea_identity_env: prod` and decrypts prod's vault into its own fact
    # precisely so this narrowing stays true.
    #
    # `dev` is kept — `infra/stacks/services/core/gitea/compose.dev.yml` still
    # runs Gitea locally. Note this is not a claim that dev is complete: only
    # `admin_password` is actually present in dev.enc.yaml today, so
    # `secrets audit dev` already reports the other two. That gap predates this
    # change and is left visible rather than hidden by narrowing `envs` to match
    # reality — which is exactly the ANSIBLE-033 failure mode.
    SecretSpec(
        key_path="apps.services.core.gitea.secret_key",
        description="Gitea internal security key",
        kind=SecretKind.RANDOM_HEX,
        length=32,
        services=("gitea",),
        rotate_note="Restart gitea. Existing sessions invalidated.",
        envs=("dev", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.core.gitea.admin_password",
        description="Gitea admin account password (break-glass; SSO is the human login path)",
        kind=SecretKind.PASSWORD,
        services=("gitea",),
        rotate_note="Change via Gitea admin UI or CLI.",
        envs=("dev", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.core.gitea.oidc_client_secret",
        description="Gitea OIDC client secret for Authelia SSO (plaintext)",
        kind=SecretKind.OIDC_CLIENT_SECRET,
        services=("gitea", "authelia"),
        rotate_note="Must also regenerate authelia.oidc_client_secret_gitea_hash.",
        envs=("dev", "prod"),
    ),
    # =========================================================================
    # N8N
    # =========================================================================
    SecretSpec(
        key_path="apps.services.automation.n8n.encryption_key",
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
    # Argo CD (hub management plane — common.enc.yaml)  [TOOL-023 / audit D64]
    # =========================================================================
    # Four of these are read by `make deploy-argocd` (Makefile ~413-416) straight
    # from common.enc.yaml (admin_password_hash, oidc_client_secret_argocd, the two
    # webhooks); admin_password (plaintext) + oidc_client_secret_argocd_hash are the
    # sibling hub secrets `credentials generate` also writes to common. The hub is a
    # single always-on management plane, not a per-spoke deployment, so its
    # credentials live in common SOPS (see CLAUDE.md "Hub credentials always in
    # common SOPS"), NOT per-env. Registered here so `secrets audit` actually checks
    # them (previously invisible → a blank hub OIDC secret reported "all present").
    # Audited under `prod` as the always-on plane;
    # common.enc.yaml merges into the prod audit. `HUB_MANAGED` = written by
    # `toolkit credentials generate`, never by per-env `secrets init`; `EXTERNAL` =
    # operator-supplied. Both are inert to init/hash/rotate (per-env machinery).
    SecretSpec(
        key_path="argocd.admin_password",
        description="Argo CD local admin account password (plaintext; CLI/apiKey fallback account)",
        kind=SecretKind.HUB_MANAGED,
        services=("argocd",),
        format_hint="plaintext password (source of argocd.admin_password_hash)",
        rotate_note="Regenerate via `toolkit credentials generate` (→ common.enc.yaml), then `make deploy-argocd`.",
        envs=("prod",),
    ),
    SecretSpec(
        key_path="argocd.admin_password_hash",
        description="Argo CD local admin account password hash (bcrypt; CLI fallback account)",
        kind=SecretKind.HUB_MANAGED,
        services=("argocd",),
        derived_from="argocd.admin_password",
        format_hint="bcrypt hash ($2y$/$2a$...)",
        rotate_note="Regenerate via `toolkit credentials generate` (→ common.enc.yaml), then `make deploy-argocd`.",
        envs=("prod",),
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_argocd",
        description="Authelia→Argo CD OIDC client secret (plaintext; injected as $oidc.authelia.clientSecret)",
        kind=SecretKind.HUB_MANAGED,
        services=("argocd", "authelia"),
        rotate_note=(
            "Regenerate via `toolkit credentials generate` (also refreshes oidc_client_secret_argocd_hash), "
            "then `make deploy-argocd`."
        ),
        envs=("prod",),
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_argocd_hash",
        description="Argon2 hash of the Authelia→Argo CD OIDC client secret (Authelia client registry)",
        kind=SecretKind.HUB_MANAGED,
        services=("authelia",),
        derived_from=f"{_AUTH}.oidc_client_secret_argocd",
        format_hint="$argon2id$v=19$...",
        rotate_note="Auto-refreshed by `toolkit credentials generate` alongside oidc_client_secret_argocd.",
        envs=("prod",),
    ),
    SecretSpec(
        key_path="argocd.slack_webhook_url",
        description="Slack incoming webhook URL for Argo CD notifications (argocd-notifications)",
        kind=SecretKind.EXTERNAL,
        services=("argocd",),
        format_hint="https://hooks.slack.com/services/...",
        rotate_note="Re-create the webhook in Slack, update common.enc.yaml, then `make deploy-argocd`.",
        envs=("prod",),
    ),
    SecretSpec(
        key_path="argocd.github_webhook_secret",
        description="Shared secret validating GitHub webhook deliveries to the Argo CD webhook receiver",
        kind=SecretKind.EXTERNAL,
        services=("argocd",),
        format_hint="opaque shared secret (must match the GitHub webhook config)",
        rotate_note="Rotate on the GitHub webhook + common.enc.yaml, then `make deploy-argocd`.",
        envs=("prod",),
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
    # Offsite backup destination (BACKUP-044 / #1056, ADR-049 D3). Stored in
    # common.enc.yaml because the pipeline spans prod (VPS) and homelab nodes, but
    # registered under `envs=("prod",)` — `envs` is the AUDIT dimension, not the
    # storage location, and there is no `common` pseudo-env: a tuple matching no
    # real env makes the secret vanish from every audit silently (ANSIBLE-033).
    # Prod is the right audit target because the critical subset exists to protect
    # prod-serving state: Headscale, Authelia, Postgres, and the Uptime Kuma
    # instance that is the monitoring of record for prod. Same pattern as the
    # Argo CD hub keys.
    #
    # A backup credential missing from the audit is the worst thing to have
    # silently absent — the failure is invisible until a restore is attempted.
    SecretSpec(
        key_path="backup.r2.access_key_id",
        description="Cloudflare R2 S3 access key id — offsite restic destination",
        kind=SecretKind.EXTERNAL,
        services=("backup",),
        format_hint="R2 API token id (not the token value)",
        rotate_note=(
            "Create a new R2 API token scoped to the kubelab-backups bucket, set both "
            "halves, then re-provision the four backup nodes. The old token must stay "
            "valid until every node has the new one, or a node silently stops backing up."
        ),
        envs=("prod",),
    ),
    SecretSpec(
        key_path="backup.r2.secret_access_key",
        description="Cloudflare R2 S3 secret access key — offsite restic destination",
        kind=SecretKind.EXTERNAL,
        services=("backup",),
        format_hint="SHA-256 of the R2 API token value; shown once, not recoverable",
        rotate_note="Rotated together with backup.r2.access_key_id — they are one credential.",
        envs=("prod",),
    ),
    # The restic repository password. restic encrypts client-side, so R2 never
    # holds plaintext and Cloudflare cannot help recover anything — this value is
    # the only key that exists. Losing it makes every backup permanently
    # unreadable while looking perfectly healthy in the bucket.
    #
    # It therefore has a SECOND home outside this repo, in a Bitwarden item, and
    # that is deliberate rather than sloppy: SOPS is decrypted by an age key that
    # a disaster destroys, so a password stored only here is unreachable in
    # exactly the scenario the backups exist for (BACKUP-044 R1, #479).
    #
    # Rotation is unusually cheap for a repository password: restic derives the
    # key that unlocks an internal master key, so `restic key add` introduces a
    # second password without re-encrypting any data.
    SecretSpec(
        key_path="backup.restic_password",
        description="restic repository password — the only key to every offsite backup",
        kind=SecretKind.RANDOM_TOKEN,
        length=48,
        services=("backup",),
        format_hint="URL-safe random token",
        rotate_note=(
            "Use `restic key add` on every repository BEFORE changing this value — a "
            "rotation that replaces it first locks you out of existing snapshots. Update "
            "the Bitwarden escrow copy in the same pass, or recovery silently regresses."
        ),
        envs=("prod",),
    ),
    SecretSpec(
        key_path="apps.services.automation.github_runner.token",
        description="GitHub PAT for self-hosted Actions runner registration",
        kind=SecretKind.EXTERNAL,
        services=("github-runner",),
        # The runner moved ace2 -> Beelink with ADR-028 / IDP-024; the note still
        # said ace2, which would send a rotation to the wrong host.
        rotate_note="Re-provision beelink (Ansible). Token must have repo + workflow scope.",
    ),
    # Dev-node machine identity (ANSIBLE-033, ADR-058 D1/D3). Lives in
    # common.enc.yaml, NOT per-env: it authenticates ace2 to GitHub, and GitHub is
    # not an environment. Audited under `staging` because that is the env ace2
    # provisions with (`make provision NODE=ace2 ENV=staging`) and common merges
    # into the staging audit — same shape as the Argo CD hub keys above, which are
    # audited under `prod`. There is no `common` pseudo-env in this catalog.
    SecretSpec(
        key_path="apps.services.automation.dev_node.github_token",
        description="Fine-grained GitHub PAT giving the ace2 dev node its own machine identity (gh + git over HTTPS)",
        kind=SecretKind.EXTERNAL,
        services=("dev-node",),
        format_hint="fine-grained PAT (github_pat_…), contents+pull-requests write, checks+statuses read, 90d expiry",
        rotate_note=(
            "EXPIRES — see docs/runbooks/dev-node-token-rotation.md. Mint a replacement, "
            "`toolkit secrets set` it in common.enc.yaml, `make provision NODE=ace2 ENV=staging "
            "TAGS=dev_node`, then revoke the old one."
        ),
        envs=("staging",),
    ),
    # Apprise notification gateway (NOTIFY-001, ADR-044). Promoted to staging+prod.
    # bot-token is shared (common SOPS); chat IDs are per-env (dedicated Telegram
    # channels per environment so prod alerts stay separate from staging). Under
    # Option B the bot-token / chat IDs are read at `secrets apply` time to render
    # the Apprise routing table (kubelab.yml); n8n no longer holds Telegram creds.
    SecretSpec(
        key_path="apps.services.automation.apprise.telegram.bot_token",
        description="Telegram bot token for the Apprise notification gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="<bot_id>:<auth_token> from @BotFather",
        rotate_note="Re-issue via @BotFather, then `secrets apply` (re-renders kubelab.yml). No pod restart needed.",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.telegram.chat_page",
        description="Telegram channel ID for the PAGE tier (push) — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="-100… channel ID (dedicated, not the hermes chat — ADR-044 C5)",
        rotate_note="Update the PAGE channel, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.telegram.chat_log",
        description="Telegram channel ID for the LOG tier (archive, no push) — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="-100… channel ID (archive tier; kubelab_bot admin — ADR-044 C4/C5)",
        rotate_note="Update the LOG channel, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    # Shared secret for the n8n /webhook/notify ingress (NOTIFY-001 criterion #4).
    # Lives in the n8n encrypted credential store (Header Auth, ADR-044 webhook-auth);
    # SOPS holds the canonical copy for recovery/rotation. No K8s SECRET_DEFINITIONS
    # mapping — n8n reads it from its own credential, not from an env var.
    # Staging and prod n8n each hold their OWN separately-configured credential
    # (different values, one per env file) — this key is env-scoped by design.
    SecretSpec(
        key_path="apps.services.automation.notify.webhook_secret",
        description="Shared secret authenticating POSTs to the n8n /webhook/notify ingress",
        kind=SecretKind.RANDOM_TOKEN,
        services=("n8n",),
        format_hint="opaque bearer token; sources send 'Authorization: Bearer <token>'",
        rotate_note="Regenerate, paste into the n8n 'notify-webhook' Header Auth credential, update every source.",
        envs=("staging", "prod"),
    ),
    # ANSIBLE-035: fleet-wide copy of the PROD n8n webhook token specifically,
    # under a DEDICATED key (not the one above) so the merge can't collide.
    # All 7 kubelab-notify@.service nodes POST to prod n8n
    # regardless of their own deploy_env (see specs/ANSIBLE-035-.../proposal.md
    # for why: alerting must not depend on ace1/staging-n8n's power state).
    # If this shared the `webhook_secret` key path above, the 3 nodes with
    # deploy_env: staging (beelink, ace1, ace2) would resolve STAGING's
    # distinct value instead — their playbooks merge common.enc.yaml with
    # staging.enc.yaml, and the env override wins — so those nodes would send
    # a token prod n8n rejects with 403. common-only storage (no per-env
    # override exists for this key) sidesteps that: every node decrypts
    # common.enc.yaml unconditionally, so this always resolves the same way.
    # Value must stay identical to the PROD entry of webhook_secret above —
    # it authenticates against the same n8n Header Auth credential.
    SecretSpec(
        key_path="apps.services.automation.notify.fleet_webhook_secret",
        description="Fleet-wide copy of prod n8n's webhook token, for bare-metal OnFailure= notify units",
        kind=SecretKind.RANDOM_TOKEN,
        services=("n8n",),
        format_hint="opaque bearer token, identical to the PROD apps.services.automation.notify.webhook_secret value",
        rotate_note=(
            "Rotate apps.services.automation.notify.webhook_secret (env=prod) first, then copy "
            "the new value here with the same command used to create it (see ANSIBLE-035), then "
            "re-provision the fleet (`make provision NODE=x TAGS=maintenance` per node) — "
            "kubelab-notify@.service reads this from a static 0600 file written at "
            "provision time, not decrypted live on the node."
        ),
        envs=("staging", "prod"),  # consumed by nodes provisioned under both envs
    ),
    # =========================================================================
    # Platform API (external — user-provided credentials)
    # =========================================================================
    # SSOT-012 PR #3 (ADR-036, 2026-05-23): SMTP moved from
    # `apps.platform.api.email_*` to the shared infra namespace
    # `infra.smtp.*`. `user` was moved to common.yaml (not a secret —
    # visible in every email sent); `pass` stays in SOPS. Consumers
    # (API + Authelia) read `INFRA_SMTP_*` env vars directly.
    SecretSpec(
        key_path="infra.smtp.pass",
        description="SMTP app password (shared: API + Authelia outbound mail)",
        kind=SecretKind.EXTERNAL,
        services=("api", "authelia"),
        rotate_note="apply-secrets for api-secrets + authelia-secrets, restart both.",
    ),
    # Shared Postgres data-service (ADR-051). This is OUR OWN DB password (not an
    # external credential) → machine-generated. `username`/`database`/`host` are
    # non-secrets in common.yaml. K8s-only (staging+prod base); dev is Docker
    # Compose with no Postgres yet. The api becomes a second consumer in PR-1b.
    SecretSpec(
        key_path="infra.postgres.password",
        description="Postgres password for the shared data-service (board projection + future pgvector)",
        kind=SecretKind.RANDOM_TOKEN,
        services=("postgres",),
        rotate_note="apply-secrets for postgres-secrets; ALTER USER + restart postgres (and api once it connects).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.platform.api.beehiiv_api_key",
        description="Beehiiv newsletter API key",
        kind=SecretKind.EXTERNAL,
        services=("api",),
        rotate_note="apply-secrets for api-secrets. Regenerate in Beehiiv dashboard.",
    ),
    # SSOT-012 (2026-05-23): apps.platform.api.beehiiv.pub_id moved from SOPS
    # to common.yaml — publication IDs are public (visible in every Beehiiv
    # embed URL) and were leaking into ConfigMaps via the SECRET_PATTERNS
    # regex gap. Companion `api_key` stays in SOPS as a true secret.
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
    # =========================================================================
    # AI services (ADR-035 Stage 1 — X-API-Key via Traefik plugin)
    # =========================================================================
    # (empty since AI-007 — Ollama was Stage 1's only registered API key)
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
            # A placeholder sentinel (REPLACE_WITH_SOPS_VALUE/CHANGE_ME) is syntactically
            # present but not configured — treat as missing (TOOL-019 / C6).
            if value is not None and str(value).strip() and not is_placeholder(value):
                result.present.append(spec.key_path)
            else:
                result.missing.append(spec.key_path)

        return result

    def audit_all(self) -> list[AuditResult]:
        """Audit all environments."""
        return [self.audit(env) for env in ("dev", "staging", "prod")]

    # ── Init (generate machine secrets) ──────────────────────────────────────

    def init_machine_secrets(
        self,
        env: str,
        dry_run: bool = False,
        force: bool = False,
        rotate: list[str] | None = None,
    ) -> dict[str, str]:
        """Generate machine-generable secrets (random tokens, hex keys, RSA, OIDC).

        Idempotent by default: secrets that already exist (non-empty) are skipped,
        so running this against a populated environment only fills the gaps and never
        clobbers a live encryption key. Use ``force=True`` to regenerate every
        machine-generable secret, or ``rotate=[key, ...]`` to regenerate only the
        named keys.

        Does NOT generate:
        - Passwords (require interactive prompt)
        - Argon2 hashes (derived from passwords)
        - CrowdSec API keys (require running container)
        - External secrets (API tokens provided by user)

        Returns dict of key_path → generated value (empty dict on validation error).
        """
        auto_kinds = {
            SecretKind.RANDOM_HEX,
            SecretKind.RANDOM_TOKEN,
            SecretKind.OIDC_CLIENT_SECRET,
            SecretKind.RSA_KEY,
        }

        rotate_set = set(rotate or [])
        if rotate_set:
            env_keys = {s.key_path for s in SECRET_CATALOG if env in s.envs}
            machine_keys = {s.key_path for s in SECRET_CATALOG if env in s.envs and s.kind in auto_kinds}
            unknown = rotate_set - env_keys
            non_machine = (rotate_set & env_keys) - machine_keys
            if unknown:
                logger.error(f"Unknown secret key(s) for {env}: {', '.join(sorted(unknown))}")
                return {}
            if non_machine:
                logger.error(f"Not machine-generable (won't rotate): {', '.join(sorted(non_machine))}")
                return {}

        # Idempotency: skip secrets already present (non-empty). force/rotate bypass it.
        present = set() if (force or rotate_set) else set(self.audit(env).present)

        generated: dict[str, str] = {}
        skipped: list[str] = []

        for spec in SECRET_CATALOG:
            if env not in spec.envs:
                continue
            if spec.kind not in auto_kinds:
                continue
            if rotate_set and spec.key_path not in rotate_set:
                continue
            if spec.key_path in present:
                skipped.append(spec.key_path)
                continue

            value = self._generate_secret(spec)
            if value:
                generated[spec.key_path] = value

        if skipped:
            logger.info(
                f"Skipped {len(skipped)} existing secret(s) (use --force to regenerate all, or --rotate KEY for one)"
            )

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
        """Decrypt and return a single secret value.

        Supports env='common' for shared secrets (common.enc.yaml).
        """
        from pathlib import Path

        secrets_path = Path(self.project_root) / "infra" / "config" / "secrets"
        sops_file = secrets_path / f"{env}.enc.yaml"
        if not sops_file.exists():
            return None

        import subprocess

        result = subprocess.run(
            ["sops", "-d", str(sops_file)],
            capture_output=True,
            text=True,
            env=age_key_env(),  # auto-discover SOPS_AGE_KEY_FILE (toolkit/core/sops.py)
        )
        if result.returncode != 0:
            return None

        import yaml

        decrypted = yaml.safe_load(result.stdout) or {}
        value = self._resolve_key(decrypted, key_path)
        return str(value) if value is not None else None

    def set_secret(self, env: str, key_path: str, value: str) -> bool:
        """Set a single secret value in the SOPS vault.

        Uses `sops set` to write the value directly into the encrypted file.
        The key_path is dot-separated (e.g., 'aws.access_key_id').
        """
        cm = self._cm(env)
        sops_file = cm.secrets_path / f"{env}.enc.yaml"

        if not sops_file.exists():
            logger.error(f"SOPS file not found: {sops_file}")
            return False

        # Convert dot path to sops JSON path: a.b.c → ["a"]["b"]["c"]
        sops_path = "".join(f'["{k}"]' for k in key_path.split("."))

        import subprocess

        result = subprocess.run(
            ["sops", "set", str(sops_file), sops_path, f'"{value}"'],
            capture_output=True,
            text=True,
            env=age_key_env(),  # auto-discover SOPS_AGE_KEY_FILE (toolkit/core/sops.py)
        )

        if result.returncode != 0:
            logger.error(f"sops set failed: {result.stderr.strip()}")
            return False

        return True

    def unset_secret(self, env: str, key_path: str) -> bool:
        """Remove a key from the SOPS vault.

        Uses `sops unset` to remove the key from the encrypted file.
        The key_path is dot-separated (e.g., 'apps.services.network').
        """
        cm = self._cm(env)
        sops_file = cm.secrets_path / f"{env}.enc.yaml"

        if not sops_file.exists():
            logger.error(f"SOPS file not found: {sops_file}")
            return False

        sops_path = "".join(f'["{k}"]' for k in key_path.split("."))

        import subprocess

        result = subprocess.run(
            ["sops", "unset", str(sops_file), sops_path],
            capture_output=True,
            text=True,
            env=age_key_env(),  # auto-discover SOPS_AGE_KEY_FILE (toolkit/core/sops.py)
        )

        if result.returncode != 0:
            logger.error(f"sops unset failed: {result.stderr.strip()}")
            return False

        return True

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
