"""Deployment management commands."""

from typing import Annotated

import typer

from toolkit.config.constants import MESSAGES
from toolkit.core.logging import logger
from toolkit.features.orchestrator import DeploymentOrchestrator
from toolkit.features.validation import (
    confirm_dangerous_operation,
    validate_environment_config,
)

app = typer.Typer(
    name="deployment",
    help="High-level deployment orchestration (setup, deploy, rollback).",
    no_args_is_help=True,
)


@app.command()
def setup(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ],
) -> None:
    """
    Bootstrap a new environment (install dependencies, setup network).
    """
    logger.section(f"Environment Setup - {env.upper()}")

    # Validate environment and get config
    env_config = validate_environment_config(env)
    logger.info(MESSAGES.INFO_PROCESSING.format(f"Setting up: {env_config.description}"))

    # Confirm dangerous operations
    confirm_dangerous_operation(env_config, "Set up environment")

    try:
        orchestrator = DeploymentOrchestrator(env)
        orchestrator.setup_environment()
        logger.success(MESSAGES.SUCCESS_COMPLETED.format(f"Environment {env} setup"))
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Environment setup", str(e)))
        raise typer.Exit(1) from None


@app.command()
def deploy(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ],
    skip_build: Annotated[
        bool,
        typer.Option(
            "--skip-build",
            help="Skip building applications",
        ),
    ] = False,
) -> None:
    """
    Orchestrate a full deployment (Build -> Infra -> Apps).

    1. Builds application artifacts/images (if not skipped)
    2. Deploys infrastructure (Ansible)
    3. Deploys/Restarts applications
    4. Runs health checks
    """
    logger.section(f"Deployment - {env.upper()}")

    # Validate environment and get config
    env_config = validate_environment_config(env)
    logger.info(MESSAGES.INFO_PROCESSING.format(f"Deploying to: {env_config.description}"))

    # Confirm dangerous operations
    confirm_dangerous_operation(env_config, "Deploy")

    try:
        orchestrator = DeploymentOrchestrator(env)
        orchestrator.deploy(skip_build=skip_build)
        logger.success(MESSAGES.SUCCESS_COMPLETED.format(f"Deployment to {env}"))
    except Exception:
        logger.error(MESSAGES.ERROR_DEPLOYMENT_FAILED)
        raise typer.Exit(1) from None


@app.command()
def status(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ],
) -> None:
    """
    Check overall deployment status (Infra + Apps).
    """
    logger.section(f"Deployment Status - {env.upper()}")

    try:
        orchestrator = DeploymentOrchestrator(env)
        orchestrator.check_status()
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Status check", str(e)))
        raise typer.Exit(1) from None


@app.command()
def backup(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ],
) -> None:
    """
    Backup all volumes and data for the environment.
    """
    logger.section(f"Backup - {env.upper()}")

    # Validate environment
    env_config = validate_environment_config(env)

    # Warn about dev backups but allow continuation
    if env == "dev":
        logger.warning(MESSAGES.WARNING_DEV_BACKUP_UNNECESSARY)
        if not logger.confirm("Continue with backup?", default=False):
            raise typer.Exit(0) from None
    else:
        confirm_dangerous_operation(env_config, "Backup environment")

    try:
        orchestrator = DeploymentOrchestrator(env)
        orchestrator.backup()
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Backup", str(e)))
        raise typer.Exit(1) from None


@app.command()
def restore(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ],
    backup_id: Annotated[
        str,
        typer.Option(
            "--backup-id",
            help="Backup ID or timestamp to restore",
        ),
    ],
) -> None:
    """
    Restore environment data from a backup.
    """
    logger.section(f"Restore - {env.upper()}")

    # Validate environment and confirm
    env_config = validate_environment_config(env)
    confirm_dangerous_operation(env_config, f"Restore from backup {backup_id}")

    try:
        orchestrator = DeploymentOrchestrator(env)
        orchestrator.restore(backup_id)
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Restore", str(e)))
        raise typer.Exit(1) from None


@app.command()
def rollback(
    env: Annotated[
        str,
        typer.Option(
            "--env",
            "-e",
            help="Target environment",
        ),
    ],
) -> None:
    """
    Revert deployment to the previous stable state.
    """
    logger.section(f"Rollback - {env.upper()}")

    # Validate environment and confirm dangerous operation
    env_config = validate_environment_config(env)
    confirm_dangerous_operation(env_config, "Rollback deployment")

    try:
        orchestrator = DeploymentOrchestrator(env)
        orchestrator.rollback()
    except Exception as e:
        logger.error(MESSAGES.ERROR_FAILED_WITH_REASON.format("Rollback", str(e)))
        raise typer.Exit(1) from None
