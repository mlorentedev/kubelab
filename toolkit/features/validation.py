"""Validation utilities for environments, components, and dependencies."""

import os
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

import typer

from toolkit.config.constants import DEFAULT_CONFIG, MESSAGES, PATH_STRUCTURES
from toolkit.config.settings import EnvironmentConfig, settings
from toolkit.core.logging import DependencyError, logger


def validate_environment_config(env: str) -> EnvironmentConfig:
    """
    Validate environment and return config.

    Args:
        env: Environment name (dev, staging, prod)

    Returns:
        EnvironmentConfig object

    Raises:
        typer.Exit: If environment is invalid
    """
    try:
        env_config = settings.get_environment(env)
        logger.info(f"Target environment: {env_config.description}")
        return env_config
    except ValueError:
        valid_envs = list(settings.environments.keys()) or DEFAULT_CONFIG.VALID_ENVIRONMENTS
        logger.error(MESSAGES.ERROR_INVALID_ENVIRONMENT.format(env, ", ".join(valid_envs)))
        raise typer.Exit(1) from None


def validate_environment(env: str | None = None) -> str:
    """Validate environment parameter (legacy function)."""
    environment = env or os.getenv("ENVIRONMENT") or DEFAULT_CONFIG.DEFAULT_ENVIRONMENT
    valid_envs = list(settings.environments.keys()) or DEFAULT_CONFIG.VALID_ENVIRONMENTS

    if environment and environment not in valid_envs:
        raise ValueError(MESSAGES.ERROR_INVALID_ENVIRONMENT.format(environment, ", ".join(valid_envs)))

    # Return validated environment or default
    return environment if environment in valid_envs else DEFAULT_CONFIG.DEFAULT_ENVIRONMENT


def confirm_dangerous_operation(env_config: EnvironmentConfig, operation: str) -> None:
    """
    Ask for confirmation on production/staging operations.

    Args:
        env_config: Environment configuration
        operation: Operation description (e.g., "Apply configuration")

    Raises:
        typer.Exit: If user declines confirmation
    """
    if env_config.requires_confirmation:
        prompt = f"⚠️  {operation} on {env_config.name.upper()}. Continue?"
        if not logger.confirm(prompt, default=False):
            logger.info(f"{operation} cancelled")
            raise typer.Exit(0) from None


def find_component_directory(component_name: str) -> Path | None:
    """
    Find the directory for a given component name.

    Searches in:
    1. Apps directory (infra/stacks/apps/)
    2. Services directory (infra/stacks/services/*)
    3. Edge directory (infra/stacks/edge/)

    Args:
        component_name: Name of the component

    Returns:
        Path to component directory, or None if not found
    """
    # Check apps
    app_dir = settings.project_root / PATH_STRUCTURES.INFRA_STACKS_APPS / component_name
    if app_dir.exists():
        return app_dir

    # Validate Services
    services_base = settings.project_root / PATH_STRUCTURES.INFRA_STACKS_SERVICES
    if services_base.exists():
        for category_dir in services_base.iterdir():
            if category_dir.is_dir() and not category_dir.name.startswith("."):
                service_path = category_dir / component_name
                if service_path.exists():
                    return service_path

    # Check edge services
    edge_path = settings.project_root / PATH_STRUCTURES.EDGE_DIR / component_name
    if edge_path.exists():
        return edge_path

    return None


def get_environment_config(env: str, config_type: str) -> str:
    """Get environment-specific configuration."""
    env_config = settings.get_environment(env)
    return getattr(env_config, config_type, "") if env_config else ""


def check_environment_safety(env: str, operation: str) -> bool:
    """Check if operation is safe for environment."""
    if operation == "deploy":
        if env == "prod":
            return logger.confirm(MESSAGES.CONFIRM_PRODUCTION_DEPLOY)
        elif env == "staging":
            logger.warning(MESSAGES.WARNING_DEPLOYING_STAGING)
    elif operation == "destroy":
        return logger.confirm(MESSAGES.CONFIRM_DESTROY_SERVICES.format(env))
    return True


def verify_required_vars(required_vars: Sequence[str], env_vars: dict[str, str] | None = None) -> bool:
    """Verify required variables are set."""
    if env_vars is None:
        env_vars = dict(os.environ)

    missing_vars = [var for var in required_vars if not env_vars.get(var)]

    if missing_vars:
        logger.error(MESSAGES.ERROR_MISSING_REQUIRED_VARS)
        for var in missing_vars:
            logger.console.print(f"  - {var}")
        return False

    return True


def validate_python_version(required_version: str) -> bool:
    """Check if current Python version meets requirements."""
    required_parts = tuple(map(int, required_version.split(".")))
    current_parts = sys.version_info[:2]
    return current_parts >= required_parts


def get_component_name(file_path: Path) -> str:
    """Extract component name from file path."""
    try:
        relative_path = file_path.relative_to(settings.project_root)
        parts = relative_path.parts
        if len(parts) < 3:
            return "unknown"

        component_parts = parts[1 : min(5, len(parts) - 1)]
        return "-".join(component_parts) if component_parts else "unknown"
    except ValueError:
        return "unknown"


# =============================================================================
# Dependency Validation
# =============================================================================


def validate_dependencies(required_only: bool = False) -> dict[str, bool]:
    """Validate that required tools are available in the system.

    Args:
        required_only: If True, only check required tools; otherwise check all tools

    Returns:
        Dictionary mapping tool names to availability status

    Raises:
        DependencyError: If any required tool is missing
    """
    tools_to_check = settings.required_tools if required_only else settings.check_tools
    results = {}

    for tool in tools_to_check:
        available = shutil.which(tool) is not None
        results[tool] = available

        if available:
            logger.info(f"✅ {tool} available")
        else:
            logger.warning(f"❌ {tool} not available")

    missing_required = [tool for tool in settings.required_tools if tool in results and not results[tool]]

    if missing_required:
        raise DependencyError(missing_required)

    return results


def validate_command_available(cmd: str, package: str | None = None) -> bool:
    """Validate that a specific command is available.

    Args:
        cmd: Command name to check
        package: Optional package name to suggest for installation

    Returns:
        True if command is available, False otherwise
    """
    if shutil.which(cmd):
        return True

    package_name = package or cmd
    logger.error(f"Command '{cmd}' not found. Please install '{package_name}'.")
    return False
