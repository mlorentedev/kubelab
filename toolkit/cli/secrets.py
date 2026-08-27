"""Unified secrets management CLI.

Single entry point for all secret operations:
  toolkit secrets edit    — Open SOPS editor
  toolkit secrets init    — Generate machine secrets
  toolkit secrets jwks    — Generate OIDC JWKS RSA key
  toolkit secrets hash    — Hash all OIDC client secrets
  toolkit secrets apply   — Push SOPS secrets to K8s cluster
  toolkit secrets audit   — Show missing/present secrets per env
  toolkit secrets show    — Display a specific secret value
  toolkit secrets catalog — List all registered secrets
"""

from __future__ import annotations

import getpass
import os
import subprocess
import sys
from typing import TYPE_CHECKING, Annotated

import typer

from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.core.sops import age_key_env

if TYPE_CHECKING:
    from toolkit.features.secrets_manager import AuditResult, SecretsManager

app = typer.Typer(
    name="secrets",
    help="Unified secrets management (SOPS vaults, K8s secrets, audit).",
    no_args_is_help=True,
)


def _get_manager() -> SecretsManager:
    """Lazy import to avoid circular deps at module level."""
    from toolkit.features.secrets_manager import secrets_manager

    return secrets_manager


def _stdin_value() -> str:
    """Read a secret value from stdin.

    Interactive TTY → prompt once with hidden input (Enter submits; no Ctrl-D).
    Piped (non-TTY) → read until EOF. A trailing newline is stripped either way.
    """
    if sys.stdin.isatty():
        return getpass.getpass("Secret value (hidden, Enter to submit): ").rstrip("\r\n")
    return sys.stdin.read().rstrip("\r\n")


# =============================================================================
# edit — Open SOPS editor
# =============================================================================


@app.command()
def edit(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
) -> None:
    """Open the SOPS-encrypted secrets file in your editor.

    Uses $EDITOR (default: nano). All changes are encrypted on save.

    Example: toolkit secrets edit --env staging
    """
    # Allow 'common' for shared SOPS file, validate others as environments
    if env != "common":
        settings.validate_environment(env)
    mgr = _get_manager()
    sops_file = mgr.get_sops_file_path(env)

    if not sops_file.exists():
        logger.error(f"SOPS file not found: {sops_file}")
        raise typer.Exit(1)

    editor = os.environ.get("EDITOR", "nano")
    logger.info(f"Opening {sops_file.name} with {editor}...")

    try:
        sops_env = {**age_key_env(), "EDITOR": editor}
        result = subprocess.run(
            ["sops", "edit", str(sops_file)],
            env=sops_env,
        )
        if result.returncode == 0:
            logger.success(f"Secrets saved ({env})")
        elif result.returncode == 200:
            logger.info("No changes made")
        else:
            logger.error(f"SOPS edit failed (exit {result.returncode})")
            raise typer.Exit(1)
    except FileNotFoundError:
        logger.error("sops is not installed")
        raise typer.Exit(1) from None


# =============================================================================
# init — Generate machine secrets
# =============================================================================


@app.command()
def init(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be generated")] = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Regenerate ALL machine secrets, even existing ones"),
    ] = False,
    rotate: Annotated[
        list[str] | None,
        typer.Option("--rotate", help="Regenerate only the given key path(s); repeatable"),
    ] = None,
) -> None:
    """Generate machine-generable secrets (random tokens, hex keys, RSA).

    Idempotent by default: existing secrets are skipped, so it is safe to run on a
    populated environment (fills only the gaps). Use `--force` to regenerate every
    machine secret, or `--rotate KEY` to regenerate specific keys.

    Does NOT generate: passwords (use `toolkit credentials generate`),
    CrowdSec API keys (requires running container), or external API tokens.

    Example: toolkit secrets init --env staging
    """
    settings.validate_environment(env)
    logger.section(f"Initialize Machine Secrets — {env.upper()}")

    mgr = _get_manager()
    generated = mgr.init_machine_secrets(env, dry_run=dry_run, force=force, rotate=rotate)

    if dry_run:
        logger.info(f"Would generate {len(generated)} secrets:")
        for key_path in sorted(generated):
            logger.info(f"  {key_path}")
    elif generated:
        logger.success(f"Generated {len(generated)} machine secrets for {env}")
        logger.info("Next steps:")
        logger.info("  1. Set passwords:  toolkit credentials generate --env " + env)
        logger.info("  2. Hash OIDC:      toolkit secrets hash --env " + env)
        if env != "dev":
            logger.info("  3. Apply to K8s:   toolkit secrets apply --env " + env)
    else:
        logger.warning("No secrets generated (all may already exist or generation failed)")


# =============================================================================
# jwks — Generate OIDC JWKS RSA key
# =============================================================================


@app.command()
def jwks(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
) -> None:
    """Generate OIDC JWKS RSA 4096 key and store in SOPS vault.

    The key is used by Authelia to sign OIDC JWT tokens.
    Also saves a PEM file at infra/config/secrets/{env}.oidc-jwks.pem.

    Example: toolkit secrets jwks --env staging
    """
    settings.validate_environment(env)
    logger.section(f"Generate JWKS Key — {env.upper()}")

    mgr = _get_manager()
    pem = mgr.generate_jwks(env)

    if pem:
        logger.success("JWKS RSA key generated and stored in SOPS")
        if env != "dev":
            logger.info("Next: toolkit secrets apply --env " + env)
    else:
        logger.error("JWKS generation failed")
        raise typer.Exit(1)


# =============================================================================
# hash — Hash all OIDC client secrets
# =============================================================================


@app.command("hash")
def hash_secrets(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
) -> None:
    """Generate Argon2 hashes for all OIDC client secrets.

    Reads plaintext OIDC secrets from SOPS, generates hashes, writes back.
    This handles: general OIDC, Grafana OIDC, MinIO OIDC client secrets.

    Example: toolkit secrets hash --env staging
    """
    settings.validate_environment(env)
    logger.section(f"Hash OIDC Client Secrets — {env.upper()}")

    mgr = _get_manager()
    hashes = mgr.hash_oidc_secrets(env)

    if hashes:
        logger.success(f"Generated {len(hashes)} hashes for {env}")
        if env != "dev":
            logger.info("Next: toolkit secrets apply --env " + env)
    else:
        logger.warning("No hashes generated (source secrets may be missing)")


# =============================================================================
# apply — SOPS → K8s
# =============================================================================


@app.command()
def apply(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")],
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be applied")] = False,
) -> None:
    """Decrypt SOPS secrets and apply as K8s Secrets to the cluster.

    Equivalent to: toolkit infra k8s apply-secrets --env ENV

    Example: toolkit secrets apply --env staging
    """
    settings.validate_environment(env)
    logger.section(f"Apply Secrets to K8s — {env.upper()}")

    mgr = _get_manager()
    if not mgr.apply_to_k8s(env, dry_run=dry_run):
        raise typer.Exit(1)


# =============================================================================
# audit — Show missing/present secrets
# =============================================================================


@app.command()
def audit(
    env: Annotated[str | None, typer.Option("--env", "-e", help="Target environment (omit for all)")] = None,
) -> None:
    """Audit secrets completeness across environments.

    Shows which secrets are present, missing, or unexpected in each
    environment's SOPS vault.

    Example:
      toolkit secrets audit                  # All environments
      toolkit secrets audit --env staging    # Staging only
    """
    mgr = _get_manager()

    if env:
        settings.validate_environment(env)
        results = [mgr.audit(env)]
    else:
        results = mgr.audit_all()

    for result in results:
        _print_audit_result(result)

    # EXPIRY IS PART OF AN AUDIT, not a separate errand.
    #
    # `check-expiry` existed as its own command and nothing ran it -- which is
    # the same shape as the finding it was built to fix: a control that reports
    # only when someone remembers is a control that does not exist. Folding it
    # in here costs nothing (this command already holds the decrypted config)
    # and attaches it to a routine that is actually performed.
    #
    # Best effort by design: an unreachable issuer must not fail an audit whose
    # subject is which secrets are PRESENT. It says so and moves on -- a
    # scheduled check that can fail loudly is the follow-up, not this.
    logger.subsection("Expiry (provider-issued credentials)")
    try:
        _report_expiry(warn_days=90)
    except Exception as exc:  # noqa: BLE001 - never let this fail the audit
        logger.warning(f"expiry not checked: {exc}")


def _report_expiry(warn_days: int) -> None:
    """Ask each issuer, report, and never raise. Shared with `check-expiry`."""
    from datetime import datetime, timezone

    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.secret_expiry import (
        PROVIDER_CHECKS,
        Expiry,
        ExpiryUnavailableError,
        resolve_expiry,
    )
    from toolkit.features.secrets_manager import SECRET_CATALOG

    merged = ConfigurationManager("common", settings.project_root).get_merged_config()

    def dig(path: str) -> str:
        node: object = merged
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return ""
            node = node[part]
        return str(node or "")

    for spec in SECRET_CATALOG:
        if resolve_expiry(spec) is not Expiry.PROVIDER:
            continue
        check = PROVIDER_CHECKS.get(spec.key_path)
        if check is None or not (value := dig(spec.key_path)):
            continue
        try:
            expires = check(value)
        except ExpiryUnavailableError as exc:
            logger.warning(f"  {spec.key_path} — could not ask the issuer: {exc}")
            continue
        if expires is None:
            logger.info(f"  {spec.key_path} — no expiry set")
            continue
        days = (expires - datetime.now(timezone.utc)).days
        line = f"  {spec.key_path} — expires {expires:%Y-%m-%d} ({days}d)"
        logger.error(line) if days < warn_days else logger.info(line)


def _print_audit_result(result: AuditResult) -> None:
    """Pretty-print an audit result."""
    from toolkit.features.secrets_manager import _CATALOG_BY_KEY

    total = len(result.present) + len(result.missing)
    pct = (len(result.present) / total * 100) if total > 0 else 0

    logger.subsection(f"{result.env.upper()} — {len(result.present)}/{total} ({pct:.0f}%)")

    if result.missing:
        logger.warning(f"Missing ({len(result.missing)}):")
        for key in sorted(result.missing):
            spec = _CATALOG_BY_KEY.get(key)
            desc = f" — {spec.description}" if spec else ""
            kind = f" [{spec.kind.value}]" if spec else ""
            logger.info(f"  {key}{kind}{desc}")

    if result.present and not result.missing:
        logger.success("All secrets present")


# =============================================================================
# show — Display a secret value
# =============================================================================


@app.command()
def show(
    key: Annotated[str | None, typer.Argument(help="Dot-separated key path (omit for all)")] = None,
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
) -> None:
    """Decrypt and display a secret from the SOPS vault.

    Example:
      toolkit secrets show --env staging
      toolkit secrets show apps.services.core.gitea.secret_key --env staging
      toolkit secrets show aws.access_key_id --env common
    """
    if env != "common":
        settings.validate_environment(env)

    if key is None:
        # Delegate to existing credentials show
        import yaml

        from toolkit.cli.credentials import _decrypt_secrets_file

        try:
            data = _decrypt_secrets_file(env)
            print(yaml.dump(data, default_flow_style=False, sort_keys=False).rstrip())
        except Exception as e:
            logger.error(f"Failed to decrypt: {e}")
            raise typer.Exit(1) from None
        return

    mgr = _get_manager()
    value = mgr.show_secret(env, key)

    if value is None:
        logger.error(f"Key '{key}' not found in {env} secrets")
        raise typer.Exit(1)

    print(value)


@app.command("set")
def set_secret(
    key: Annotated[str, typer.Argument(help="Dot-separated key path (e.g., aws.access_key_id)")],
    value: Annotated[str | None, typer.Argument(help="Secret value to store (omit when using --stdin)")] = None,
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "common",
    use_stdin: Annotated[
        bool,
        typer.Option(
            "--stdin",
            help="Read the value from stdin: prompts if interactive (Enter submits), reads the pipe otherwise",
        ),
    ] = False,
) -> None:
    """Set a secret value in the SOPS vault.

    The value can be passed as an argument or supplied via --stdin. Use --stdin for
    values that start with '-' (e.g. Telegram chat IDs) and to keep secrets out of
    shell history and process args. On a terminal, --stdin prompts once with hidden
    input (Enter submits — no Ctrl-D); piped, it reads until EOF:

      toolkit secrets set <key> --env staging --stdin            # interactive prompt
      printf -- '-1004…' | toolkit secrets set <key> --env staging --stdin   # piped

    Example:
      toolkit secrets set aws.access_key_id AKIA... --env common
      printf %s "$TOKEN" | toolkit secrets set apps.x.token --env staging --stdin
    """
    valid_envs = ("common", "dev", "staging", "prod")
    if env not in valid_envs:
        logger.error(f"Invalid env: {env}. Must be one of: {', '.join(valid_envs)}")
        raise typer.Exit(1)

    if use_stdin and value is not None:
        logger.error("Pass the value as an argument OR via --stdin, not both")
        raise typer.Exit(1)
    if use_stdin:
        value = _stdin_value()
        if not value:
            logger.error("--stdin given but no value was provided")
            raise typer.Exit(1)
    elif value is None:
        logger.error("Provide a VALUE argument or use --stdin")
        raise typer.Exit(1)

    mgr = _get_manager()
    if mgr.set_secret(env, key, value):
        logger.success(f"Secret '{key}' set in {env}")
    else:
        logger.error(f"Failed to set secret '{key}' in {env}")
        raise typer.Exit(1)


@app.command("rotate")
def rotate_secret(
    key: Annotated[str, typer.Argument(help="Dot-separated key path from SECRET_CATALOG")],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "prod",
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip the confirmation prompt")] = False,
) -> None:
    """Rotate ONE credential, and stop before the cluster.

    Until this existed the only way to change a single credential was
    `credentials generate`, which rewrites 24 prod secrets and 2 hub secrets in
    one shot -- so rotating an exposed Argo CD password also rotated Grafana,
    MinIO, Uptime Kuma and every OIDC client secret.

    IT DOES NOT APPLY TO THE CLUSTER, ON PURPOSE. Prod runs `selfHeal: true`.
    Applying a rotation that git does not yet carry is not a shortcut, it is an
    outage: measured 2026-08-23, Argo CD reverted Authelia to the committed
    config and the freshly rotated client secrets stopped being accepted. Landing
    goes through commit -> PR -> merge -> sync, and the output says so.

    Refuses what it must not do: secrets minted elsewhere (their procedure is
    printed instead), immutable secrets whose rotation is really a migration, and
    keys absent from the catalog, which have no declared consumers to restart.

    Example:
      toolkit secrets rotate argocd.admin_password --env common
    """
    from toolkit.features.secrets_manager import RotationRefused

    valid_envs = ("common", "dev", "staging", "prod")
    if env not in valid_envs:
        logger.error(f"Invalid env: {env}. Must be one of: {', '.join(valid_envs)}")
        raise typer.Exit(1)

    if not yes and not typer.confirm(f"Rotate '{key}' in {env}?"):
        logger.info("Aborted — nothing was written")
        raise typer.Exit(1)

    mgr = _get_manager()
    try:
        plan = mgr.rotate_secret(env, key)
    except RotationRefused as refusal:
        logger.error(str(refusal))
        raise typer.Exit(2) from refusal

    logger.success(f"Rotated {plan.key_path} in {plan.env}")
    for path in plan.derived:
        logger.info(f"  re-derived: {path}")

    logger.warning("NOT applied to the cluster. It is not rotated until it is merged:")
    for index, step in enumerate(plan.next_steps, start=1):
        logger.info(f"  {index}. {step}")


# =============================================================================
# unset — Remove a secret from the SOPS vault
# =============================================================================


@app.command("unset")
def unset_secret(
    key: Annotated[str, typer.Argument(help="Dot-separated key path (e.g., apps.services.network)")],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "common",
) -> None:
    """Remove a key from the SOPS vault.

    Example:
      toolkit secrets unset apps.services.network --env prod
      toolkit secrets unset apps.testing.old_key --env staging
    """
    valid_envs = ("common", "dev", "staging", "prod")
    if env not in valid_envs:
        logger.error(f"Invalid env: {env}. Must be one of: {', '.join(valid_envs)}")
        raise typer.Exit(1)

    mgr = _get_manager()
    if mgr.unset_secret(env, key):
        logger.success(f"Secret '{key}' removed from {env}")
    else:
        logger.error(f"Failed to remove secret '{key}' from {env}")
        raise typer.Exit(1)


# =============================================================================
# catalog — List all registered secrets
# =============================================================================


@app.command()
def catalog(
    env: Annotated[str | None, typer.Option("--env", "-e", help="Filter by environment")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show full details")] = False,
) -> None:
    """List all secrets in the catalog with descriptions.

    Example:
      toolkit secrets catalog
      toolkit secrets catalog --env staging -v
    """
    mgr = _get_manager()
    specs = mgr.get_catalog(env)

    table = logger.table(f"Secret Catalog ({len(specs)} entries)")
    table.add_column("Key Path", style="cyan", no_wrap=True)
    table.add_column("Kind", style="yellow")
    table.add_column("Services", style="green")

    if verbose:
        table.add_column("Description")
        table.add_column("Rotate Note", style="red")

    for spec in specs:
        services = ", ".join(spec.services) if spec.services else "-"
        row = [spec.key_path, spec.kind.value, services]
        if verbose:
            row.extend([spec.description, spec.rotate_note or "-"])
        table.add_row(*row)

    logger.console.print(table)


@app.command("check-expiry")
def check_expiry(
    warn_days: Annotated[int, typer.Option("--warn-days", help="Fail below this many days remaining")] = 90,
    ssh_target: Annotated[
        str | None,
        typer.Option("--ssh", help="Where headscale runs; defaults to the VPS from the SSOT"),
    ] = None,
) -> None:
    """Ask the issuing services when the provider-issued credentials expire.

    The catalog says how to rotate every secret and said nothing about when any
    of them dies. Rotation is a procedure someone follows on purpose; expiry is
    a date that arrives whether or not anyone is looking.

    ASKED, NEVER REMEMBERED. A date recorded in this repository would drift the
    moment a key is re-minted, and it would drift in the safe-looking direction
    -- still reporting "fine" about a key replaced with a shorter-lived one.

    Exits 2, not 1, when the service cannot be reached: a check that could not
    run must never be mistaken for one that found nothing.
    """
    from datetime import datetime, timezone

    from toolkit.config.settings import settings as _settings
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.secret_expiry import (
        PROVIDER_CHECKS,
        Expiry,
        ExpiryUnavailableError,
        headscale_apikeys,
        resolve_expiry,
    )
    from toolkit.features.secrets_manager import SECRET_CATALOG

    # DERIVED, never a literal. This defaulted to `deployer@162.55.57.175` --
    # both halves hardcoded, both of them SSOT values, in a repository whose own
    # rule reads "Never hardcode IPs/CIDRs in K8s manifests, tests, or toolkit
    # code". Raised by review on #1247.
    #
    # The PUBLIC ip, not the Tailscale one: Headscale *is* the VPN, so a check
    # that reaches it over the VPN cannot report on a VPN that is down. Same
    # reason `networking.vps.ansible_host` uses the public address.
    if ssh_target is None:
        _net = ConfigurationManager("common", _settings.project_root).get_merged_config()["networking"]
        ssh_target = f"{_net['ssh_users']['cloud']}@{_net['vps']['public_ip']}"

    logger.section("Provider-issued credential expiry")

    unreachable: list[str] = []
    expiring = []

    # --- Everything the issuer can be asked about directly -------------------
    merged = ConfigurationManager("common", _settings.project_root).get_merged_config()

    def _dig(path: str) -> str:
        node: object = merged
        for part in path.split("."):
            if not isinstance(node, dict) or part not in node:
                return ""
            node = node[part]
        return str(node or "")

    for spec in SECRET_CATALOG:
        if resolve_expiry(spec) is not Expiry.PROVIDER:
            continue
        check = PROVIDER_CHECKS.get(spec.key_path)
        if check is None:
            continue  # Headscale keys are handled below, by asking the server.
        value = _dig(spec.key_path)
        if not value:
            logger.warning(f"{spec.key_path}  declared PROVIDER but absent from SOPS")
            continue
        try:
            expires = check(value)
        except ExpiryUnavailableError as exc:
            logger.error(f"{spec.key_path}  CANNOT CHECK: {exc}")
            unreachable.append(spec.key_path)
            continue
        if expires is None:
            logger.warning(f"{spec.key_path}  no expiry set (valid until revoked)")
            continue
        days = (expires - datetime.now(timezone.utc)).days
        line = f"{spec.key_path}  expires {expires:%Y-%m-%d}  ({days}d)"
        if days < warn_days:
            logger.error(line)
            expiring.append(spec.key_path)
        else:
            logger.success(line)

    # --- Headscale, which is asked for all its keys at once -------------------
    try:
        keys = headscale_apikeys(ssh_target)
    except ExpiryUnavailableError as exc:
        logger.error(f"headscale  CANNOT CHECK: {exc}")
        raise typer.Exit(2) from exc

    for key in sorted(keys, key=lambda k: k.expires_at):
        line = f"{key.prefix}  expires {key.expires_at:%Y-%m-%d}  ({key.days_left}d)"
        if key.days_left < warn_days:
            logger.error(line)
            expiring.append(key.prefix)
        else:
            logger.success(line)

    if unreachable:
        logger.error(f"{len(unreachable)} credential(s) could not be checked: {unreachable}")
        raise typer.Exit(2)

    if expiring:
        logger.error(
            f"{len(expiring)} credential(s) expire within {warn_days} days: {expiring}. "
            "Each fails SILENTLY at the moment it is needed rather than when it expires: "
            "a Headscale key leaves the next hub recreate unable to clear its stale node, "
            "so it registers as <host>-<random> and breaks the inventory and kubeconfig; "
            "a GitHub PAT leaves the runner unable to register, or the dev node unable to "
            "clone. Nothing raises an alarm on the expiry date itself."
        )
        raise typer.Exit(1)
    logger.success(f"{len(keys)} provider-issued credentials, none expiring within {warn_days} days")


@app.command("preauth-keys")
def preauth_keys(
    expire: Annotated[
        list[str] | None,
        typer.Option("--expire", help="Expire the pre-auth key with this id; repeatable"),
    ] = None,
    ssh_target: Annotated[
        str | None,
        typer.Option("--ssh", help="Where headscale runs; defaults to the VPS from the SSOT"),
    ] = None,
) -> None:
    """Report the tailnet admission tickets that are still live, and expire the ones you name.

    Reports by default and acts only when told to -- the same shape as
    `backup-schedule`, so the invocation you reach for while unsure is the safe one.

    Why this needed its own verb: `check-expiry` asks about API *keys* only, so
    pre-auth keys appeared in no report at all. On 2026-08-23 three were found
    live, reusable and never used, valid into 2027. Nothing had gone wrong --
    nobody had ever been in a position to look, and absence from a report nobody
    wrote is not evidence of absence.

    Why they are worth looking at: an API key administers Headscale, but a
    pre-auth key admits a machine to the mesh, and here the mesh IS the perimeter
    (staging is VPN-only, with no second gate behind it). A `reusable` key that
    has not expired is a standing invitation for as long as it lives.

    Expiring is not the whole retirement. When the key is also stored in SOPS,
    remove the value AND its SECRET_CATALOG entry in the same change: `secrets
    audit` reports either half left behind, as `missing` or as `unexpected`.

    Examples:
      toolkit secrets preauth-keys                 # report only
      toolkit secrets preauth-keys --expire 20     # expire key id 20
    """
    from toolkit.config.settings import settings as _settings
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.secret_expiry import (
        ExpiryUnavailableError,
        expire_headscale_preauthkey,
        headscale_preauthkeys,
    )

    # Derived, never a literal -- and the PUBLIC ip, for the reason check-expiry
    # gives: Headscale is the VPN, so reaching it over the VPN cannot report on a
    # VPN that is down.
    if ssh_target is None:
        _net = ConfigurationManager("common", _settings.project_root).get_merged_config()["networking"]
        ssh_target = f"{_net['ssh_users']['cloud']}@{_net['vps']['public_ip']}"

    logger.section("Headscale pre-auth keys")

    try:
        keys = headscale_preauthkeys(ssh_target)
    except ExpiryUnavailableError as err:
        # Exit 2, not 1: a check that could not run must never read as a clean one.
        logger.error(str(err))
        raise typer.Exit(2) from err

    live = [k for k in keys if k.is_live]
    logger.info(f"{len(keys)} pre-auth key(s) total, {len(live)} still live")
    for key in live:
        logger.warning(f"  id={key.key_id:<4} {key.prefix}  owner={key.owner}  expires {key.expires_at:%Y-%m-%d}")
        logger.info(f"       {key.risk}")

    if not expire:
        if live:
            logger.info("Report only. Expire with: toolkit secrets preauth-keys --expire <id>")
        return

    by_id = {k.key_id: k for k in keys}
    for key_id in expire:
        target = by_id.get(key_id)
        if target is None:
            logger.error(f"no pre-auth key with id {key_id} — refusing to guess")
            raise typer.Exit(1)
        if not target.is_live:
            logger.info(f"  id={key_id} already expired, nothing to do")
            continue
        try:
            expire_headscale_preauthkey(ssh_target, key_id)
        except ExpiryUnavailableError as err:
            logger.error(str(err))
            raise typer.Exit(2) from err
        logger.success(f"  expired id={key_id} ({target.prefix}, owner {target.owner})")


@app.command("sync-secret-manager")
def sync_secret_manager(
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Compare and report without writing to Secret Manager")
    ] = False,
) -> None:
    """Deliver the GCP hub's boot secrets to Google Secret Manager (one-way).

    SOPS stays the SSOT. This copies named values out to the one channel a
    recreated hub can reach at boot -- a MIG rebuilds it from a fresh disk with
    no age key, no kubeconfig and no operator (GCP-001 F1, ADR-063 D7). Drift is
    resolved by re-running this, never by reading back.

    Two input classes: the entries tagged in SECRET_CATALOG, and each spoke's
    Argo CD ServiceAccount token and CA -- which Kubernetes generates and this
    reads live, so the spokes must be REACHABLE NOW. For staging that means the
    homelab is powered on. Whatever is unreachable is reported by name and a
    later re-run completes it.

    Example:
      toolkit secrets sync-secret-manager --dry-run
      toolkit secrets sync-secret-manager
    """
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.gcp_secret_sync import GcloudMissingError, sync_all

    cm = ConfigurationManager("common", settings.project_root)
    merged = cm.get_merged_config()

    project_id = merged.get("networking", {}).get("gcp", {}).get("project_id", "")
    if not project_id:
        logger.error("networking.gcp.project_id is not set in common.yaml")
        raise typer.Exit(1)

    logger.section(f"Secret Manager sync -> {project_id}" + (" (dry-run)" if dry_run else ""))
    try:
        results = sync_all(merged, project_id, dry_run=dry_run)
    except GcloudMissingError as exc:
        logger.error(str(exc))
        raise typer.Exit(1) from exc

    # Names and actions only. A value never reaches this table, by construction:
    # SyncResult has no field that could carry one.
    #
    # A DRY RUN SAYS SO IN EVERY LINE, in the future tense. It used to print
    # `created  <name>` -- byte-identical to a real run -- so the only way to
    # know nothing had happened was to remember which flag you passed. In a
    # secrets tool that is how someone concludes a delivery occurred that did
    # not, or panics that one did. The feature already carried the distinction
    # in `detail`; nothing displayed it.
    for result in results:
        # "would created" is not English; the actions are stored past-tense.
        base = {"created": "create", "updated": "update"}.get(result.action, result.action)
        verb = f"would {base}" if dry_run and result.action != "failed" else result.action
        line = f"{verb:<14} {result.secret_id}"
        if result.action == "failed":
            logger.error(f"{line}  {result.detail}")
        elif result.action == "unchanged":
            logger.info(line)
        else:
            logger.success(line)

    failed = [r for r in results if r.action == "failed"]
    if failed:
        logger.error(f"{len(failed)} of {len(results)} secrets did not sync; re-run once the cause is fixed")
        raise typer.Exit(1)
    if dry_run:
        logger.success(f"{len(results)} secrets would be in sync — nothing was written")
    else:
        logger.success(f"{len(results)} secrets in sync")
