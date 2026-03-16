"""Credential generation and GitHub secrets management commands."""

import subprocess
from typing import Annotated, Any

import typer
import yaml

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.config.settings import PROJECT_ROOT, settings
from toolkit.core.logging import logger
from toolkit.features.credentials import credentials_manager
from toolkit.features.github_secrets import github_secrets_manager

app = typer.Typer(
    name="credentials",
    help="Generate credentials and manage GitHub secrets.",
    no_args_is_help=True,
)


def _resolve_secret_value(data: dict[str, Any], key_path: str) -> Any:
    """Traverse nested dict by dot-separated key path."""
    keys = key_path.split(".")
    current = data
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def _decrypt_secrets_file(env: str) -> dict[str, Any]:
    """Decrypt SOPS secrets file and return as dict."""
    secrets_file = PROJECT_ROOT / PATH_STRUCTURES.CONFIG_SECRETS_DIR / f"{env}.enc.yaml"
    if not secrets_file.exists():
        logger.error(f"Secrets file not found: {secrets_file}")
        raise typer.Exit(1)

    result = subprocess.run(
        ["sops", "-d", "--output-type", "yaml", str(secrets_file)],
        capture_output=True,
        text=True,
        check=True,
    )
    return yaml.safe_load(result.stdout) or {}


@app.command("show")
def show_secrets(
    key: Annotated[
        str | None,
        typer.Argument(help="Dot-separated key path (e.g., 'apps.authelia.admin_password'). Omit to show all secrets."),
    ] = None,
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
) -> None:
    """Decrypt and display secrets from SOPS-encrypted file."""
    settings.validate_environment(env)

    try:
        secrets = _decrypt_secrets_file(env)
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to decrypt secrets: {e.stderr.strip()}")
        raise typer.Exit(1) from None
    except FileNotFoundError:
        logger.error("sops is not installed")
        raise typer.Exit(1) from None

    if key:
        value = _resolve_secret_value(secrets, key)
        if value is None:
            logger.error(f"Key '{key}' not found in {env} secrets")
            raise typer.Exit(1) from None
        if isinstance(value, dict):
            print(yaml.dump(value, default_flow_style=False, sort_keys=False).rstrip())
        else:
            print(value)
    else:
        print(yaml.dump(secrets, default_flow_style=False, sort_keys=False).rstrip())


@app.command("hash-password")
def hash_password(
    key_path: Annotated[
        str,
        typer.Argument(help="Dot-separated path to the secret key (e.g., 'apps.authelia.users_admin_password_hash')"),
    ],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
) -> None:
    """
    Interactively prompts for a password, generates its Argon2 hash,
    and updates the specified key in the SOPS-encrypted secrets file.
    """
    credentials_manager.update_hashed_secret(key_path=key_path, env=env)


@app.command("extract-common")
def extract_common(
    source: Annotated[str, typer.Option("--from", "-f", help="Source environment")] = "dev",
    clean: Annotated[bool, typer.Option("--clean", help="Remove extracted keys from source")] = False,
) -> None:
    """Extract shared infrastructure secrets into common.enc.yaml.

    Moves external credentials (Cloudflare, DockerHub, Gmail, Hetzner, etc.)
    from a per-environment SOPS file to common.enc.yaml so they are
    automatically available to all environments via the merge chain:
    common.yaml → {env}.yaml → common.enc.yaml → {env}.enc.yaml

    Example: toolkit credentials extract-common --from dev --clean
    """
    if not credentials_manager.extract_common_secrets(source, clean_source=clean):
        raise typer.Exit(1)


@app.command("init-env")
def init_env(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment to initialize")],
) -> None:
    """Initialize a new environment's SOPS file and generate service secrets.

    Shared secrets come from common.enc.yaml automatically (via merge chain).
    This command only generates the env-specific secrets (Authelia, BasicAuth, etc.).

    Prerequisites: common.enc.yaml must exist (run extract-common first).

    Example: toolkit credentials init-env --env staging
    """
    credentials_manager.setup_authelia_secrets(env=env, auto_update=True)


@app.command("generate")
def generate_credentials(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
    auto_update: Annotated[
        bool,
        typer.Option(
            "--auto-update",
            help="Automatically update SOPS and restart affected services",
        ),
    ] = False,
) -> None:
    """
    Generate all primary authentication credentials (Authelia and Basic Auth).

    Prints secrets for manual copy to SOPS file.

    Generates:
    - Authelia admin password hash (Argon2)
    - OIDC HMAC, Session, Storage Encryption keys
    - JWT secret for password reset
    - OIDC client secret and hash
    - JWKS RSA private key (saved as file)
    - Basic auth user/password/credentials (htpasswd bcrypt)
    """
    credentials_manager.setup_authelia_secrets(env=env, auto_update=auto_update)


@app.command()
def setup_gh_secrets(
    env: Annotated[
        str,
        typer.Argument(help="Target environment"),
    ] = "dev",
) -> None:
    """
    Sync environment configuration to GitHub repository secrets.

    Reads from YAML+SOPS configuration and updates matching GitHub secrets.
    """
    settings.validate_environment(env)

    synced_count = github_secrets_manager.sync_env_to_secrets(env)

    if synced_count > 0:
        logger.success(f"Synced {synced_count} secrets to GitHub for {env} environment")
    else:
        logger.warning(MESSAGES.WARNING_CREDENTIALS_NO_SECRETS_SYNCED)


@app.command()
def list_gh_secrets() -> None:
    """
    List all configured secrets in the GitHub repository.
    """
    logger.section("GitHub Secrets")

    if not github_secrets_manager.check_gh_cli():
        raise typer.Exit() from None

    secrets = github_secrets_manager.list_secrets()

    if secrets:
        logger.info(f"Found {len(secrets)} configured GitHub secrets:")
        for secret in sorted(secrets):
            logger.info(f"  - {secret}")
    else:
        logger.warning(MESSAGES.WARNING_CREDENTIALS_NO_GITHUB_SECRETS)


@app.command()
def set_gh_secret(
    name: Annotated[str, typer.Argument(help="Secret name")],
    value: Annotated[str, typer.Argument(help="Secret value")],
    env: Annotated[
        str | None,
        typer.Option(
            "--env",
            "-e",
            help="Target environment (adds environment suffix)",
        ),
    ] = None,
) -> None:
    """
    Set a single GitHub secret.
    """
    logger.section("Set GitHub Secret")

    if not github_secrets_manager.check_gh_cli():
        raise typer.Exit() from None

    secret_name = f"{name}_{env.upper()}" if env else name
    logger.info(f"Setting secret: {secret_name}")

    if github_secrets_manager.set_secret(secret_name, value):
        logger.success(MESSAGES.SUCCESS_CREDENTIALS_SECRET_SET.format(secret_name))
    else:
        logger.error(MESSAGES.ERROR_CREDENTIALS_SECRET_SET_FAILED.format(secret_name))
        raise typer.Exit() from None


@app.command()
def delete_gh_secret(
    name: Annotated[str, typer.Argument(help="Secret name")],
    env: Annotated[
        str | None,
        typer.Option(
            "--env",
            "-e",
            help="Target environment (adds environment suffix)",
        ),
    ] = None,
) -> None:
    """
    Delete a single GitHub secret.
    """
    logger.section("Delete GitHub Secret")

    if not github_secrets_manager.check_gh_cli():
        raise typer.Exit() from None

    secret_name = f"{name}_{env.upper()}" if env else name

    if not logger.confirm(f"Delete secret '{secret_name}'?", default=False):
        logger.info(MESSAGES.INFO_CREDENTIALS_SECRET_DELETION_CANCELLED)
        return

    if github_secrets_manager.delete_secret(secret_name):
        logger.success(MESSAGES.SUCCESS_CREDENTIALS_SECRET_DELETED.format(secret_name))
    else:
        logger.error(MESSAGES.ERROR_CREDENTIALS_SECRET_DELETE_FAILED.format(secret_name))
        raise typer.Exit() from None
