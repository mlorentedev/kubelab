"""Credential generation and GitHub secrets management commands."""

from typing import Annotated

import typer

from toolkit.config.constants import MESSAGES
from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.credentials import credentials_manager
from toolkit.features.github_secrets import github_secrets_manager

app = typer.Typer(
    name="credentials",
    help="Generate credentials and manage GitHub secrets.",
    no_args_is_help=True,
)


@app.command("hash-password")
def hash_password(
    key_path: Annotated[
        str,
        typer.Argument(
            help="Dot-separated path to the secret key "
            "(e.g., 'apps.authelia.users_admin_password_hash')"
        ),
    ],
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
) -> None:
    """
    Interactively prompts for a password, generates its Argon2 hash,
    and updates the specified key in the SOPS-encrypted secrets file.
    """
    credentials_manager.update_hashed_secret(key_path=key_path, env=env)


@app.command("generate")
def generate_credentials(
    env: Annotated[str, typer.Option("--env", "-e", help="Target environment")] = "dev",
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
    credentials_manager.setup_authelia_secrets(env=env)


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
        logger.error(
            MESSAGES.ERROR_CREDENTIALS_SECRET_DELETE_FAILED.format(secret_name)
        )
        raise typer.Exit() from None
