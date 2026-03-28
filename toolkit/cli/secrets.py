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

import os
import subprocess
from typing import TYPE_CHECKING, Annotated

import typer

from toolkit.config.settings import settings
from toolkit.core.logging import logger

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
        sops_env = {**os.environ, "EDITOR": editor}
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
) -> None:
    """Generate all machine-generable secrets (random tokens, hex keys, RSA).

    Does NOT generate: passwords (use `toolkit credentials generate`),
    CrowdSec API keys (requires running container), or external API tokens.

    Example: toolkit secrets init --env staging
    """
    settings.validate_environment(env)
    logger.section(f"Initialize Machine Secrets — {env.upper()}")

    mgr = _get_manager()
    generated = mgr.init_machine_secrets(env, dry_run=dry_run)

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
    value: Annotated[str, typer.Argument(help="Secret value to store")],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "common",
) -> None:
    """Set a secret value in the SOPS vault.

    Example:
      toolkit secrets set aws.access_key_id AKIA... --env common
      toolkit secrets set apps.testing.authelia_test_password "pass" --env staging
    """
    valid_envs = ("common", "dev", "staging", "prod")
    if env not in valid_envs:
        logger.error(f"Invalid env: {env}. Must be one of: {', '.join(valid_envs)}")
        raise typer.Exit(1)

    mgr = _get_manager()
    if mgr.set_secret(env, key, value):
        logger.success(f"Secret '{key}' set in {env}")
    else:
        logger.error(f"Failed to set secret '{key}' in {env}")
        raise typer.Exit(1)


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
