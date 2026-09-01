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

import re
import secrets as stdlib_secrets
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

from toolkit.config.constants import AUTHELIA_CONFIG, PATH_STRUCTURES, is_placeholder
from toolkit.config.settings import PROJECT_ROOT
from toolkit.core.logging import logger
from toolkit.core.sops import age_key_env
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.secret_expiry import Expiry

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
    # Declares that this secret is DELIVERED to Google Secret Manager for the GCP
    # hub's cloud-init to read at boot (ADR-063 D7, GCP-001 finding F1).
    #
    # Delivery, not storage, and the distinction is the same one `envs` gets
    # wrong often enough to be a documented gotcha: SOPS remains the SSOT and the
    # only place a value is ever authored. Secret Manager is a one-way copy that
    # a recreated hub can reach when nothing else on the machine can -- it has no
    # SOPS age key, no kubeconfig and no operator. Drift is resolved by
    # re-syncing, never by reading back.
    #
    # Tagging here rather than in a second list is deliberate: a standalone list
    # of "secrets to sync" would be a second declaration of a fact this catalog
    # already owns, free to disagree with it silently.
    sync_to_secret_manager: bool = False
    # WHEN this secret stops working, as a category -- never as a date.
    #
    # The catalog already says how to rotate every secret and said nothing about
    # when any of them dies. Rotation is a procedure someone follows on purpose;
    # expiry is a date that arrives whether or not anyone is looking. Measured
    # 2026-08-22: `aws.headscale_api_key` expires 2027-03-27 and nothing in this
    # repository knew.
    #
    # A DATE IS DELIBERATELY NOT STORED HERE. It would be a second declaration
    # that drifts the moment a key is re-minted, and it drifts in the
    # safe-looking direction -- still saying "fine" about a key replaced with a
    # shorter-lived one. `Expiry.PROVIDER` means "ask the service that issued
    # it"; `toolkit secrets check-expiry` does the asking.
    #
    # Defaults to UNKNOWN so a new entry surfaces as unclassified rather than
    # being quietly assumed immortal.
    expiry: Expiry = Expiry.UNKNOWN


# -- Authelia base path shortcut --
_AUTH = "apps.services.security.authelia"

SECRET_CATALOG: list[SecretSpec] = [
    # Registered on 2026-08-26 by the reverse audit (#833), which is what showed
    # these were live and unowned. `secrets_manager.py` already argued for one of
    # them in prose — "Companion `api_key` stays in SOPS as a true secret" — and
    # then never registered it, which is the exact gap the reverse direction
    # exists to close: a decision recorded in a comment is not a registry entry.
    SecretSpec(
        key_path="apps.services.observability.uptime_kuma.admin_password",
        description="Uptime Kuma admin password",
        kind=SecretKind.PASSWORD,
        services=("uptime_kuma",),
        rotate_note="Reconciled by `credentials generate` via _reconcile_external_credentials.",
    ),
    SecretSpec(
        key_path="apps.services.observability.uptime_kuma.api_key",
        expiry=Expiry.NEVER,
        description="Uptime Kuma API key, for programmatic monitor management",
        kind=SecretKind.EXTERNAL,
        services=("uptime_kuma",),
        rotate_note="Re-issue in the Uptime Kuma UI; consumed by `toolkit monitoring`.",
    ),
    SecretSpec(
        key_path="apps.testing.authelia_test_password",
        description="Password for the e2e `testuser` Authelia account",
        kind=SecretKind.PASSWORD,
        services=("authelia",),
        format_hint="Plain text; the argon2 hash of it is a separate catalog entry",
        rotate_note="Re-hash into users_testuser_password_hash, then apply-secrets. Used by tests/e2e/conftest.py.",
    ),
    SecretSpec(
        key_path="hetzner.api_key",
        expiry=Expiry.NEVER,
        description="Hetzner Cloud API token — Terraform and the DR runbook",
        kind=SecretKind.EXTERNAL,
        services=("terraform",),
        rotate_note="Re-issue in the Hetzner console. See docs/runbooks/runbook-disaster-recovery.md.",
    ),
    SecretSpec(
        key_path="dockerhub.username",
        expiry=Expiry.NEVER,
        description="Docker Hub account for CI image push",
        kind=SecretKind.EXTERNAL,
        services=("ci",),
        rotate_note="Mirrored to GitHub Actions as DOCKERHUB_USERNAME.",
    ),
    SecretSpec(
        key_path="dockerhub.token",
        expiry=Expiry.NEVER,
        description="Docker Hub access token for CI image push",
        kind=SecretKind.EXTERNAL,
        services=("ci",),
        rotate_note="Re-issue in Docker Hub, then mirror to GitHub Actions as DOCKERHUB_TOKEN.",
    ),
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
    # Tracks the identity SSOT `apps.auth.identities.operator` (AUTH-004 C1,
    # ADR-062 D3; was `apps.auth.admin_username` under SSOT-014b). The key stays
    # STATIC on purpose: SECRET_CATALOG is a module-level constant, and deriving
    # this path at import time would make importing the secrets module read and
    # merge `common.yaml` — a config read on every `toolkit` invocation, and an
    # import that fails when the config does.
    #
    # The lockstep the old comment asked someone to remember is now enforced
    # instead: `tests/test_admin_identity_ssot.py` asserts this key matches the
    # identity the SSOT resolves, so a rename that forgets this line fails in
    # CI rather than silently pointing audit/init/rotation at a path nobody
    # writes. A written reminder is not a mechanism (lesson-365).
    SecretSpec(
        key_path=f"{_AUTH}.users_operator_password_hash",
        description="Argon2 hash of admin user password (username from apps.auth.identities.operator)",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from="(interactive password prompt)",
        format_hint="$argon2id$v=19$m=65536,t=3,p=4$...",
        rotate_note="User must know the new password to login.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.users_manu_password_hash",
        description=(
            "Argon2 hash of the superadmin's first-factor password (username from apps.auth.identities.superadmin)"
        ),
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from="(interactive password prompt)",
        format_hint="$argon2id$v=19$m=65536,t=3,p=4$...",
        # PROD ONLY, and the narrowness is the point. `envs` is the AUDIT
        # dimension (ANSIBLE-033): declaring all three would make dev and staging
        # report a gap for a key that was never written there, which is the noise
        # that trains an operator to stop reading the audit.
        envs=("prod",),
        rotate_note=(
            "The superadmin must know the new password to log in. NOTE: `manu` is "
            "not yet a declared Authelia user (apps.services.security.authelia.users "
            "holds `identity: operator` and `testuser`), so this hash has NO consumer "
            "today -- it is AUTH-004 Part 1 preparation, deliberate rather than "
            "forgotten. Declaring the user is coupled to R1b, which stays parked: "
            "`manu` has no OIDC linkage, so its first SSO login is one-shot on the "
            "sole admin account."
        ),
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
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_vikunja",
        description="Vikunja OIDC client secret (plaintext)",
        kind=SecretKind.OIDC_CLIENT_SECRET,
        services=("authelia", "vikunja"),
        rotate_note="Must also regenerate the vikunja hash.",
    ),
    SecretSpec(
        key_path=f"{_AUTH}.oidc_client_secret_vikunja_hash",
        description="Argon2 hash of Vikunja OIDC client secret",
        kind=SecretKind.ARGON2_HASH,
        services=("authelia",),
        derived_from=f"{_AUTH}.oidc_client_secret_vikunja",
        format_hint="$argon2id$v=19$...",
        rotate_note="Auto-derived from oidc_client_secret_vikunja.",
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
    SecretSpec(
        key_path="apps.services.observability.grafana.alerts_ro_token",
        description="Grafana Viewer service-account token for `toolkit obs alerts` (OBS-019)",
        kind=SecretKind.EXTERNAL,
        services=("grafana",),
        rotate_note=(
            "Minted via Grafana's service-account API (Viewer role, SA 'obs-alerts-ro'), "
            "not user-provided. Rotate: delete the token in Grafana, mint a new one, "
            "`secrets set` here, then `make apply-secrets`."
        ),
        # Minted with no `secondsToLive`, so Grafana itself never expires it —
        # unlike `gcp.headscale_api_key` (Expiry.PROVIDER), this one has no
        # remote lifetime to ask about; only a manual revoke ends it.
        expiry=Expiry.NEVER,
        # Prod token minting is blocked by #951 (prod admin credential rejected).
        # Staging carries a real value; prod will not until #951 closes, and
        # `make secrets-audit` will correctly report that as a gap until then.
        envs=("staging", "prod"),
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
    SecretSpec(
        key_path="apps.services.core.gitea.bot_token",
        description=(
            "Scoped Gitea API token for the machine identity "
            "(apps.auth.identities.machine); the account has no interactive login"
        ),
        # EXTERNAL, not RANDOM_TOKEN: the value is minted BY Gitea and only Gitea
        # can honour it, so `secrets init` must never generate one — a locally
        # generated string would look like a valid secret, pass every audit, and
        # authenticate nothing.
        kind=SecretKind.EXTERNAL,
        services=("gitea",),
        rotate_note=(
            "Revoke the old token in Gitea, delete this key, then re-provision the "
            "Beelink — the mint task is gated on this key being absent. Never rotate by "
            "minting a second token: the account would hold two live credentials and "
            "nothing records which consumer holds which."
        ),
        # NEVER, and measured rather than assumed. `EXTERNAL` means somebody else
        # issued it, which is usually a reason to classify it PROVIDER and go ask
        # — but Gitea grants access tokens no lifetime at all. Its token API
        # returns `created_at`, `last_used_at`, `scopes`, `token_last_eight` and
        # no expiry field of any kind, so there is nothing to ask and nothing to
        # renew; the token lives until it is revoked. Declaring PROVIDER would
        # oblige a checker that could only ever answer "no expiry", which is a
        # control that reports nothing.
        expiry=Expiry.NEVER,
        # prod, not dev: Gitea's identity environment is prod (`gitea_identity_env`),
        # which is why the play loads a separate `gitea_secrets` tree. `envs` is the
        # audit dimension — which environments must HAVE this — not the file it lives
        # in, and a tuple matching no real env drops it from every audit silently
        # (ANSIBLE-033).
        envs=("prod",),
    ),
    SecretSpec(
        key_path="apps.services.core.gitea.admin_token",
        description=(
            "Gitea API token for the superadmin (apps.auth.identities.superadmin); "
            "creates organizations and reads whole-forge state for the reconciler"
        ),
        # EXTERNAL for the same reason as `bot_token`: Gitea mints it, only Gitea
        # honours it, and a generated string would pass every audit while
        # authenticating nothing.
        kind=SecretKind.EXTERNAL,
        services=("gitea",),
        rotate_note=(
            "Mint at Settings > Applications with `write:organization` and `read:repository`. "
            "TWO reasons this is the superadmin's and not the bot's, and only the first is "
            "obvious: Gitea puts the creating account in a new organization's `Owners` team, so "
            "ADR-065 D1 (the bot owns nothing) forbids the bot creating them; and the RECONCILER'S "
            "READS need it too, because the bot cannot see an organization it is not a member of "
            "and would report an existing private org as absent. Revoke the old token before "
            "storing a new one — two live credentials with nothing recording which consumer holds "
            "which is the shape `bot_token`'s note already warns about."
        ),
        # NEVER, for the reason measured on `bot_token` above: Gitea's token API
        # carries no expiry field at all, so PROVIDER would oblige a checker that
        # could only ever answer "no expiry".
        expiry=Expiry.NEVER,
        # prod, matching `bot_token` — Gitea's identity environment is prod, and
        # `envs` is the audit dimension rather than the file (ANSIBLE-033).
        envs=("prod",),
    ),
    SecretSpec(
        key_path="apps.services.core.gitea.github_migration_token",
        description=(
            "Fine-grained GitHub PAT that Gitea's migration endpoint uses to READ "
            "issues, pull requests and contents from the repositories ADR-065 moves"
        ),
        # EXTERNAL for the same reason as `bot_token`: GitHub issues it, only
        # GitHub honours it, and a locally generated string would pass every audit
        # while authenticating nothing. Unlike `bot_token` it is used by the
        # RECONCILER calling Gitea, not by Gitea calling us — it is passed per
        # migration request and (with `mirror: false`, which is what ADR-065's
        # "move" means) Gitea has nothing to re-sync and so nothing to store.
        kind=SecretKind.EXTERNAL,
        services=("gitea",),
        rotate_note=(
            "Read-only by construction — Contents/Metadata/Issues/Pull requests, no write "
            "anywhere, because the migration only reads from GitHub and Gitea writes on its "
            "own side. Regenerate at github.com/settings/personal-access-tokens, then "
            "`toolkit secrets set <key> --env prod --stdin`. Verify by consequence before "
            "trusting it: a granted private repo answers 200 and one outside the grant "
            "answers 404 (NOT 403 — GitHub does not confirm existence to an unauthorised "
            "caller, and reading that 404 as 'the repo is gone' is the wrong lesson)."
        ),
        # PROVIDER, and it genuinely resolves: `github_pat_expiry` reads the
        # `github-authentication-token-expiration` header GitHub returns on any
        # authenticated call. Measured 2026-08-28 against this very token —
        # 2026-10-27, 59 days left. This is the module's "asked, not remembered"
        # rule paying off: no date is recorded here to drift.
        expiry=Expiry.PROVIDER,
        # prod, matching `bot_token` above: the forge's identity environment is
        # prod, and `envs` is the audit dimension rather than the file (ANSIBLE-033).
        envs=("prod",),
    ),
    # =========================================================================
    # Vikunja (IDP-035)
    # =========================================================================
    SecretSpec(
        key_path="apps.services.core.vikunja.db_password",
        description="PostgreSQL password for vikunja tenant role",
        kind=SecretKind.RANDOM_TOKEN,
        services=("vikunja", "postgres"),
        rotate_note="Update role password in postgres, restart vikunja",
    ),
    SecretSpec(
        key_path="apps.services.core.vikunja.jwt_secret",
        description="Vikunja JWT signing secret for sessions and API tokens",
        kind=SecretKind.RANDOM_TOKEN,
        services=("vikunja",),
        rotate_note="Invalidates active JWT sessions. Users must re-login.",
    ),
    SecretSpec(
        key_path="apps.services.core.vikunja.oidc_client_secret",
        description="Vikunja OIDC client secret for Authelia SSO",
        kind=SecretKind.OIDC_CLIENT_SECRET,
        services=("vikunja", "authelia"),
        rotate_note="Regenerate secret in Authelia and update vikunja deployment.",
    ),
    SecretSpec(
        key_path="apps.services.core.vikunja.r2_access_key",
        description="Cloudflare R2 Access Key ID for Vikunja attachments",
        kind=SecretKind.PASSWORD,
        services=("vikunja",),
        rotate_note="Update R2 bucket token in Cloudflare, reapply secrets.",
    ),
    SecretSpec(
        key_path="apps.services.core.vikunja.r2_secret_key",
        description="Cloudflare R2 Secret Access Key for Vikunja attachments",
        kind=SecretKind.PASSWORD,
        services=("vikunja",),
        rotate_note="Update R2 bucket token in Cloudflare, reapply secrets.",
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
    SecretSpec(
        key_path="apps.services.automation.n8n.vikunja_api_token",
        description="Vikunja API token for n8n automation workflows",
        kind=SecretKind.EXTERNAL,
        expiry=Expiry.NEVER,
        services=("n8n", "vikunja"),
        rotate_note="Update API token in Vikunja and redeploy n8n.",
    ),
    SecretSpec(
        key_path="apps.services.automation.n8n.forge_webhook_secret",
        description="Shared HMAC secret for GitHub and Gitea webhooks to n8n",
        kind=SecretKind.RANDOM_HEX,
        length=32,
        services=("n8n",),
        rotate_note="Update webhook secret in GitHub/Gitea repositories.",
    ),
    SecretSpec(
        key_path="apps.services.automation.n8n.slack_signing_secret",
        description="Slack app signing secret for ChatOps slash commands",
        kind=SecretKind.EXTERNAL,
        expiry=Expiry.NEVER,
        services=("n8n",),
        rotate_note="Update signing secret in Slack App settings.",
    ),
    # =========================================================================
    # MinIO
    # =========================================================================
    # No `root_user` entry: MinIO's root account NAME is configuration, not a
    # credential. It resolves from `apps.auth.identities.superadmin` on both
    # delivery paths — `k8s_secrets._build_dynamic_literals` for the cluster and
    # `provision-bee.yml` for the Beelink Compose stack, which is the one that
    # actually runs. Registering a name here made it a thing `credentials
    # generate` rewrites (ADR-062 D3, AUTH-004 AC1). A value for the old key may
    # still sit in the `.enc.yaml` files; nothing reads it.
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
        sync_to_secret_manager=True,
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
        sync_to_secret_manager=True,
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
        expiry=Expiry.NEVER,
        description="Slack incoming webhook URL for Argo CD notifications (argocd-notifications)",
        kind=SecretKind.EXTERNAL,
        services=("argocd",),
        format_hint="https://hooks.slack.com/services/...",
        rotate_note="Re-create the webhook in Slack, update common.enc.yaml, then `make deploy-argocd`.",
        envs=("prod",),
        sync_to_secret_manager=True,
    ),
    SecretSpec(
        key_path="argocd.github_webhook_secret",
        expiry=Expiry.NEVER,
        description="Shared secret validating GitHub webhook deliveries to the Argo CD webhook receiver",
        kind=SecretKind.EXTERNAL,
        services=("argocd",),
        format_hint="opaque shared secret (must match the GitHub webhook config)",
        rotate_note="Rotate on the GitHub webhook + common.enc.yaml, then `make deploy-argocd`.",
        envs=("prod",),
        sync_to_secret_manager=True,
    ),
    # =========================================================================
    # GCP hub (ADR-063) — read by cloud-init from Secret Manager, not by a human
    # =========================================================================
    SecretSpec(
        key_path="gcp.headscale_api_key",
        expiry=Expiry.PROVIDER,
        description="Headscale API key the GCP hub reads at boot (node recycle + pre-auth minting)",
        kind=SecretKind.EXTERNAL,
        services=("headscale", "gcp1"),
        format_hint="hskey-api-... (Headscale API key, NOT a pre-auth key)",
        rotate_note=(
            "Mint on the VPS with `headscale apikeys create`, update common.enc.yaml, "
            "then re-run the Secret Manager sync. No hub restart needed: cloud-init "
            "reads it only at boot, so the new value is picked up by the next recreate."
        ),
        # `prod`, NOT `common`. `envs` is the AUDIT dimension, not the file the
        # value lives in: it declares which environments must have this secret.
        # There is no `common` pseudo-env, so `envs=("common",)` matches no real
        # env and the secret vanishes from every audit silently (ANSIBLE-033).
        # The value itself lives in common.enc.yaml alongside the other hub keys.
        envs=("prod",),
        # The ONE secret cloud-init can read at boot, and deliberately the only
        # one until Phase 2: with it the node mints its own short-lived pre-auth
        # key instead of carrying a stored one (finding F2).
        sync_to_secret_manager=True,
    ),
    SecretSpec(
        key_path="gcp.billing_account_id",
        expiry=Expiry.NEVER,
        description="Billing account holding the monthly platform credit; budgets attach to it",
        kind=SecretKind.EXTERNAL,
        services=("terraform",),
        format_hint="XXXXXX-XXXXXX-XXXXXX",
        rotate_note=(
            "Not rotatable — it identifies an account, not a credential. It changes only "
            "if the project is relinked to a different billing account, which would also "
            "move it off the credit: re-run `gcloud billing projects describe kubelab-hub` "
            "and confirm `billingAccountName` before editing this."
        ),
        # Not a credential: nothing can be spent with it absent IAM. It is in SOPS
        # because this repository is PUBLIC and git history is permanent, so a
        # payment-account identifier would be disclosed forever at no benefit --
        # and the cost of storing it here is one line. AC1 is still satisfied: the
        # spec's verification.md records WHERE it lives and its last six digits, so
        # a future reader re-checks rather than re-discovers.
        envs=("prod",),
        # NOT synced to Secret Manager: cloud-init has no use for it. Only the
        # billing Terraform root reads it, and that runs from the workstation.
        # Syncing it would put it on the very project whose spend it governs.
        sync_to_secret_manager=False,
    ),
    # =========================================================================
    # Infrastructure (external — not auto-generated, but must exist in SOPS)
    # =========================================================================
    SecretSpec(
        key_path="cloudflare.api_token",
        expiry=Expiry.PROVIDER,
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
        expiry=Expiry.NEVER,
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
        expiry=Expiry.NEVER,
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
        expiry=Expiry.PROVIDER,
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
        expiry=Expiry.PROVIDER,
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
        expiry=Expiry.NEVER,
        description="Telegram bot token for the Apprise notification gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="<bot_id>:<auth_token> from @BotFather",
        rotate_note="Re-issue via @BotFather, then `secrets apply` (re-renders kubelab.yml). No pod restart needed.",
        envs=("staging", "prod"),
    ),
    # Slack side of the Apprise routing table. Read by `k8s_secrets.py:294` and
    # asserted by `tests/test_k8s_secrets_apprise.py:68`, and registered here only
    # on 2026-08-26 — the reverse audit (#833) is what surfaced that five live
    # secrets had no catalog entry at all. `envs` matches where the values
    # actually are, per ANSIBLE-033: staging and prod, not dev.
    SecretSpec(
        key_path="apps.services.automation.apprise.slack.webhook_alerts",
        expiry=Expiry.NEVER,
        description="Slack incoming webhook, ALERT tier — the Slack half of the notification fabric — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="https://hooks.slack.com/services/…",
        rotate_note="Re-issue in Slack, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.slack.webhook_agent",
        expiry=Expiry.NEVER,
        description="Slack incoming webhook, AGENT tier — agent-originated notifications — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="https://hooks.slack.com/services/…",
        rotate_note="Re-issue in Slack, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.slack.webhook_deployments",
        expiry=Expiry.NEVER,
        description="Slack incoming webhook, DEPLOYMENT tier — deploy notifications — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="https://hooks.slack.com/services/…",
        rotate_note="Re-issue in Slack, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.slack.webhook_log",
        expiry=Expiry.NEVER,
        description="Slack incoming webhook, LOG tier — archive, no push — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="https://hooks.slack.com/services/…",
        rotate_note="Re-issue in Slack, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.slack.webhook_vault",
        expiry=Expiry.NEVER,
        description="Slack incoming webhook, VAULT tier — knowledge-plane notifications — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="https://hooks.slack.com/services/…",
        rotate_note="Re-issue in Slack, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.telegram.chat_page",
        expiry=Expiry.NEVER,
        description="Telegram channel ID for the PAGE tier (push) — Apprise gateway",
        kind=SecretKind.EXTERNAL,
        services=("apprise",),
        format_hint="-100… channel ID (dedicated, not the hermes chat — ADR-044 C5)",
        rotate_note="Update the PAGE channel, then `secrets apply` (re-renders kubelab.yml).",
        envs=("staging", "prod"),
    ),
    SecretSpec(
        key_path="apps.services.automation.apprise.telegram.chat_log",
        expiry=Expiry.NEVER,
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
        expiry=Expiry.NEVER,
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
        expiry=Expiry.NEVER,
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
        expiry=Expiry.NEVER,
        description="Zoho OAuth client ID",
        kind=SecretKind.EXTERNAL,
        services=("api",),
        rotate_note="apply-secrets for api-secrets. Regenerate in Zoho API console.",
    ),
    SecretSpec(
        key_path="apps.platform.api.zoho_client_secret",
        expiry=Expiry.NEVER,
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


def secret_manager_name(key_path: str) -> str:
    """The Secret Manager id for a SOPS key path, by rule rather than by choice.

    The two systems name things differently and neither can adopt the other's
    convention: SOPS paths are dotted (`argocd.admin_password_hash`), and a
    Secret Manager id accepts only `[A-Za-z0-9_-]` -- a dot is rejected outright.

    So a translation has to exist. What matters is that it exists ONCE. Naming
    each secret by hand on the GCP side would be a second declaration of an
    identity the catalog already owns, and the two would be free to disagree in
    the one direction nothing catches: cloud-init asking for a name the sync
    never wrote, discovered unattended after a preemption.

    The rule keeps the FULL path rather than the trailing leaf, so two secrets
    whose leaves match -- `argocd.admin_password_hash` and a future
    `gcp.admin_password_hash` -- cannot silently overwrite each other in what is
    a flat namespace on the GCP side.

    It is NOT injective, and pretending otherwise would be the more dangerous
    error. Both `.` and `_` collapse to `-`, so `a.b_c` and `a.b.c` produce the
    same id and the second write would silently replace the first. No current
    pair collides; `tests/test_secret_manager_sync.py` asserts that over the
    union of both input classes, which is where a future addition would be
    caught -- at the moment it is added, rather than at 3am on a hub that booted
    with another secret's value.
    """
    name = key_path.replace(".", "-").replace("_", "-")
    # Assert rather than sanitise: every catalog key is already in this shape, so
    # a violation means an assumption broke somewhere upstream.
    if not re.fullmatch(r"[A-Za-z0-9-]{1,255}", name):
        raise ValueError(f"{key_path!r} does not map to a valid Secret Manager id (got {name!r})")
    return name


def secrets_synced_to_secret_manager() -> tuple[SecretSpec, ...]:
    """The SOPS-authored half of what the GCP hub reads at boot (ADR-063 D7).

    The synced set has TWO classes and this is only one of them. The other --
    each spoke's Argo CD ServiceAccount token and cluster CA -- is not authored
    in SOPS at all: Kubernetes generates it, `make register-spoke` reads it live
    out of the spoke's `argocd-manager-token` Secret, and no human ever writes
    it. Declaring it here would assert an origin it does not have, which is the
    scalar-vs-derivation error ADR-063 D4 exists to name. It is derived from the
    `argocd.spokes` keys in common.yaml instead, at sync time.

    So a caller wanting "everything the hub can read" must union both classes,
    and anything asserting against the Terraform module's IAM bindings must do
    the same or it will report a false gap.
    """
    return tuple(s for s in SECRET_CATALOG if s.sync_to_secret_manager)


# =============================================================================
# Audit Result
# =============================================================================


#: SOPS writes its own metadata into every encrypted file. It is not a secret
#: anyone declares, so it must never be reported as an orphan.
_SOPS_METADATA_KEY = "sops"


#: Where the frozen orphan list lives. Its own header explains the ratchet; the
#: short version is that `orphan_key_paths` has always detected these and the
#: audit has always exited 0, so seventeen standing warnings hid the eighteenth.
ORPHAN_BASELINE_PATH = Path(__file__).resolve().parents[2] / "infra/config/orphan-secrets-baseline.yaml"


def baselined_orphans() -> dict[str, str]:
    """The accepted orphans, as `key_path -> reason`.

    A MISSING OR UNREADABLE FILE IS NOT AN EMPTY BASELINE. Returning `{}` on
    error would turn every frozen orphan into a fresh failure and, far worse, a
    typo in the path would make the whole ratchet silently permissive the day
    someone moved the file. It raises instead: a broken baseline is a broken
    guard, and a guard that cannot be read must not report success (lesson-306).
    """
    if not ORPHAN_BASELINE_PATH.exists():
        raise FileNotFoundError(
            f"orphan baseline missing at {ORPHAN_BASELINE_PATH}. It is not optional: "
            "without it the audit cannot tell frozen debt from a new orphan."
        )
    data = yaml.safe_load(ORPHAN_BASELINE_PATH.read_text(encoding="utf-8")) or {}
    entries = data.get("orphans") or {}
    if not isinstance(entries, dict):
        raise ValueError(f"{ORPHAN_BASELINE_PATH}: `orphans` must be a mapping of key_path -> reason")
    return {str(k): str(v) for k, v in entries.items()}


def unbaselined_orphans(decrypted: dict[str, Any]) -> list[str]:
    """Orphans that are NOT frozen in the baseline — the ones that fail the audit.

    This is the whole enforcement surface. Everything else about orphans is a
    report; this is the part that says no.
    """
    accepted = baselined_orphans()
    return [k for k in orphan_key_paths(decrypted) if k not in accepted]


def orphan_key_paths(decrypted: dict[str, Any]) -> list[str]:
    """Leaf key paths present in the vault that no `SECRET_CATALOG` entry owns.

    The reverse of what `audit` has always done. `audit` iterates the catalog
    and asks whether each entry has a value; nothing asked whether a value has
    an entry, so a secret whose catalog entry was removed — or that was never
    registered — stayed in the vault permanently and invisibly. `credentials
    generate` keeps rewriting whatever it seeds, so an orphan is not inert: it
    is a value something may still overwrite and nothing reads.

    Deliberately NOT filtered by `envs`. A key registered for prod only is not
    an orphan when auditing staging — it has an owner, just not here — and
    conflating "no entry at all" with "not expected in this environment" would
    recreate the ANSIBLE-033 failure mode from the other side.

    **Returns key paths and never values.** The transcript is a durable artifact
    and nothing scans it; a function that walks a decrypted vault must be
    incapable of emitting what it walked, not merely careful about it.
    """
    owned = set(_CATALOG_BY_KEY)
    orphans: list[str] = []

    def walk(node: Any, prefix: str) -> None:
        if not isinstance(node, dict):
            if prefix and prefix not in owned:
                orphans.append(prefix)
            return
        for key, value in node.items():
            if not prefix and key == _SOPS_METADATA_KEY:
                continue
            path = f"{prefix}.{key}" if prefix else key
            if path in owned:
                continue  # an owned subtree is owned whole; do not descend into it
            walk(value, path)

    walk(decrypted, "")
    return sorted(orphans)


@dataclass
class AuditResult:
    """Result of auditing secrets for an environment."""

    env: str
    present: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    unexpected: list[str] = field(default_factory=list)


class RotationRefused(Exception):
    """A rotation this command must not perform, with the reason and the real procedure.

    Refusing is a feature, not a gap. Three kinds of secret cannot be rotated by
    generating a new random value, and each fails differently if you try:

    EXTERNAL/CROWDSEC_API -- the value is minted by another system. Writing a
    fresh random string into SOPS produces a credential that authenticates
    against nothing, and the failure surfaces at the next boot rather than here.

    IMMUTABLE -- the value has already encrypted or signed state that still
    exists. Overwriting `storage_encryption_key` does not rotate anything, it
    makes Authelia's database unreadable. These are not rotations, they are
    migrations.

    Not in the catalog -- `SECRET_CATALOG` is the authoritative registry. A key
    absent from it has no declared consumers, so no restart list can be derived
    and the rotation would land silently.
    """


@dataclass(frozen=True)
class RotationPlan:
    """What a rotation changed, and what still has to happen for it to take effect.

    The second half is the point. Measured 2026-08-23: a rotation was applied to
    prod while git still held the old values, and Argo CD -- doing exactly its
    job under `selfHeal` -- reverted the cluster to a configuration that rejected
    the new credentials. Rotating is not landing, and a rotation that reports
    only what it wrote invites precisely that incident.
    """

    key_path: str
    env: str
    derived: tuple[str, ...] = ()
    restart_services: tuple[str, ...] = ()
    note: str = ""

    @property
    def next_steps(self) -> tuple[str, ...]:
        """The ordered remainder: commit, land, then restart the consumers.

        Order is load-bearing. Restarting a consumer before the new value is in
        git means it picks up a credential the reverted config will reject; that
        is the failure mode this ordering exists to prevent.
        """
        steps = [
            f"git add -A && git commit -m 'chore(secrets): rotate {self.key_path} ({self.env})'",
            "open a PR and merge it -- until then Argo CD will revert this on the next reconcile",
        ]
        if self.restart_services:
            steps.append(
                "after the merge syncs, restart the consumers so they read the new value: "
                + ", ".join(self.restart_services)
            )
        return tuple(steps)


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

        # The reverse direction, which `AuditResult.unexpected` has declared
        # since it was written and nothing ever populated — and which
        # `cli/secrets.py` promises to the operator in its own help text.
        result.unexpected = orphan_key_paths(decrypted)

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

        NEVER regenerates a secret in ``IMMUTABLE_SECRETS``, whatever the flags say.
        That sentence used to be false and the gap was not theoretical: all four
        immutable secrets are ``RANDOM_TOKEN``, which is a kind this function
        regenerates, and both ``force`` and ``rotate`` deliberately bypass the
        idempotency check that was the only thing standing in the way. Measured
        2026-08-23 with ``--force --dry-run`` against prod: it listed
        ``storage_encryption_key`` among the 19 it would write. Executing that does
        not rotate a credential -- it makes Authelia's database unreadable and takes
        every registered second factor with it.

        ``credentials generate`` has always preserved these. Two commands reaching
        the same value with only one of them guarded is the whole defect.

        Does NOT generate:
        - Passwords (require interactive prompt)
        - Argon2 hashes (derived from passwords)
        - CrowdSec API keys (require running container)
        - External secrets (API tokens provided by user)
        - Immutable secrets (see above)

        Returns dict of key_path → generated value (empty dict on validation error).
        """
        from toolkit.features.credentials import IMMUTABLE_SECRETS

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
            # Refuse the whole run rather than silently doing the safe subset: someone
            # who named an immutable key is acting on a belief about what it does, and
            # a partial success would leave that belief intact.
            immutable = rotate_set & IMMUTABLE_SECRETS
            if immutable:
                logger.error(
                    f"Refusing to regenerate immutable secret(s): {', '.join(sorted(immutable))}. "
                    "These encrypt or sign state that still exists -- overwriting "
                    "storage_encryption_key orphans Authelia's database rather than "
                    "rotating anything. Replacing one is a migration, not a rotation."
                )
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
            # Before the kind check would let force through. Immutability outranks
            # every flag: `--force` means "regenerate what is generable", and these
            # are not -- their current value is load-bearing state, not a credential
            # that happens to already exist.
            if spec.key_path in IMMUTABLE_SECRETS:
                logger.warning(f"  Preserving immutable secret: {spec.key_path}")
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

    def rotate_secret(self, env: str, key_path: str) -> RotationPlan:
        """Rotate ONE catalog entry and stop short of the cluster.

        The module docstring has promised `rotate (regenerate + propagate)` since
        it was written and nothing implemented it, so the only way to change one
        credential was `credentials generate`, which rewrites 24 prod secrets and
        2 hub secrets at once. That is why `rotate_note` entries describe
        procedures in prose: with no verb to carry them, a note is all there is,
        and `aws.headscale_preauth_key` sat unrotated from March to August.

        Writes through `sops set`, which edits in place rather than rewriting the
        file. A rotation done here is therefore visible as a ciphertext change on
        exactly the keys it touched -- auditable afterwards with a plain
        `git diff --numstat`, which is not true of a full regeneration.

        Deliberately does NOT apply to the cluster. See RotationPlan.
        """
        from toolkit.features.credentials import IMMUTABLE_SECRETS

        spec = next((s for s in SECRET_CATALOG if s.key_path == key_path), None)
        if spec is None:
            raise RotationRefused(
                f"{key_path!r} is not in SECRET_CATALOG, the authoritative registry. "
                "Register it there first: without a spec there are no declared "
                "consumers, so nothing can tell you what to restart afterwards."
            )

        if key_path in IMMUTABLE_SECRETS:
            raise RotationRefused(
                f"{key_path!r} is immutable: it has already encrypted or signed state "
                "that still exists, so overwriting it destroys that state rather than "
                "rotating a credential. This is a migration, not a rotation."
            )

        if spec.kind in (SecretKind.EXTERNAL, SecretKind.CROWDSEC_API):
            raise RotationRefused(
                f"{key_path!r} is minted by another system, not generated here. "
                "A random value written into SOPS would authenticate against nothing "
                "and fail at next boot instead of now.\n\nProcedure:\n"
                + (spec.rotate_note or "no rotate_note recorded — add one to the catalog")
            )

        if spec.kind == SecretKind.HUB_MANAGED:
            raise RotationRefused(
                f"{key_path!r} is HUB_MANAGED, which the catalog declares inert to the "
                "per-env machinery (init/hash/rotate): hub credentials live in "
                "common.enc.yaml and are written as a set by `credentials generate`.\n\n"
                "That is honoured here rather than worked around, but it IS the "
                "remaining half of #1338: rotating one hub credential still means "
                "rotating all of them. Granular hub rotation needs the batch write in "
                "credentials.py to be splittable first.\n\nProcedure today:\n"
                + (spec.rotate_note or "no rotate_note recorded — add one to the catalog")
            )

        if env not in spec.envs:
            raise RotationRefused(
                f"{key_path!r} is not declared for env {env!r} (declared: {', '.join(spec.envs)}). "
                "Note `envs` is the audit dimension, not the file the value lives in."
            )

        value = self._generate_secret(spec)
        if not value:
            raise RotationRefused(
                f"no generator for kind {spec.kind.value!r}; {key_path!r} cannot be rotated by this command."
            )

        if not self.set_secret(env, key_path, value):
            raise RotationRefused(f"failed to write {key_path!r} to the {env} vault")

        derived = self._rotate_derived(env, key_path, value)
        return RotationPlan(
            key_path=key_path,
            env=env,
            derived=derived,
            restart_services=spec.services,
            note=spec.rotate_note,
        )

    def _rotate_derived(self, env: str, source_path: str, source_value: str) -> tuple[str, ...]:
        """Regenerate every catalog entry declaring `derived_from` this key.

        A hash left pointing at the previous plaintext is worse than an unrotated
        secret: the credential changes and nothing accepts it, so the rotation
        reads as done while the service is down.
        """
        written: list[str] = []
        for spec in SECRET_CATALOG:
            if spec.derived_from != source_path or env not in spec.envs:
                continue
            cm = self._credentials_manager()
            if spec.kind == SecretKind.ARGON2_HASH:
                digest = cm.generate_argon2_hash(source_value)
            elif spec.kind == SecretKind.HTPASSWD:
                digest = cm.generate_bcrypt_hash(source_value)
            else:
                logger.warning(f"  no derivation for {spec.key_path} (kind {spec.kind.value})")
                continue
            if self.set_secret(env, spec.key_path, digest):
                written.append(spec.key_path)
        return tuple(written)

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
