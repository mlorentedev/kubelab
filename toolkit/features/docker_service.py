"""Unified Docker Compose service management.

Consolidates functionality from:
- docker_manager.py (low-level Docker operations)
- component_manager.py (component-level operations)
- apps_manager.py (app-level operations)
"""

import os
import subprocess
from pathlib import Path
from typing import Any

import typer
import yaml

from toolkit.config.constants import (
    DOCKER_CONFIG,
    MESSAGES,
)
from toolkit.config.settings import PlatformSettings
from toolkit.core.logging import PlatformError, logger
from toolkit.features import command
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.validation import find_component_directory


class DockerService:
    """Unified Docker Compose operations for all components (apps, services, edge)."""

    def __init__(self, settings: PlatformSettings):
        """Initialize Docker service manager.

        Args:
            settings: Platform settings instance
        """
        self.settings = settings

    def _get_execution_env(self, environment: str) -> dict[str, str]:
        """Get environment variables for execution (System + Config + Secrets)."""
        config_manager = ConfigurationManager(environment)

        # Get project variables
        project_vars = config_manager.get_env_vars()

        # Merge with current system environment (to keep PATH, etc.)
        full_env = os.environ.copy()

        # Filter out non-string values (like lists/dicts used for templates)
        safe_vars = {k: str(v) for k, v in project_vars.items() if isinstance(v, (str, int, float, bool))}

        full_env.update(safe_vars)

        return full_env

    def _get_compose_cmd(self, service_dir: Path, environment: str, action: str) -> list[str]:
        """Build the docker compose command with correct files."""
        config_manager = ConfigurationManager(environment)
        compose_files = config_manager.get_compose_files(service_dir)

        if not compose_files:
            logger.error(f"No compose files found in {service_dir} for {environment}")
            raise typer.Exit(1)

        return [*DOCKER_CONFIG.DOCKER_COMPOSE_CMD, *compose_files, action]

    # =========================================================================
    # Low-Level Operations (from docker_manager.py)
    # =========================================================================

    def validate_volume_mounts(self, service_dir: Path, environment: str) -> bool:
        """Validate that all local volume mount sources exist.

        Args:
            service_dir: Base directory for resolving relative paths
            environment: Target environment

        Returns:
            True if all volume sources exist, False otherwise
        """
        try:
            full_env = self._get_execution_env(environment)
            cmd = self._get_compose_cmd(service_dir, environment, "config")

            result = subprocess.run(
                cmd,
                cwd=self.settings.project_root,  # Changed from service_dir to project_root
                env=full_env,
                capture_output=True,
                text=True,
                check=False,
            )

            if result.returncode != 0:
                logger.warning(f"Could not parse compose file for volume validation: {result.stderr}")
                return True  # Skip validation if we can't parse

            # Parse the full YAML output
            import yaml

            try:
                compose_config = yaml.safe_load(result.stdout)
            except yaml.YAMLError:
                logger.warning("Could not parse docker compose config output.")
                return True

            missing_files = []

            # Iterate over services
            services = compose_config.get("services", {})
            for _service_name, service_config in services.items():
                volumes = service_config.get("volumes", [])
                for volume in volumes:
                    # Docker compose config returns volumes as dicts or strings
                    source = None
                    if isinstance(volume, dict):
                        if volume.get("type") == "bind":
                            source = volume.get("source")
                    elif isinstance(volume, str):
                        parts = volume.split(":")
                        if len(parts) >= 2:
                            source = parts[0]

                    if not source:
                        continue

                    # Skip named volumes (not paths)
                    if not (source.startswith("/") or source.startswith("./") or source.startswith("../")):
                        continue

                    source_path = Path(source)
                    if not source_path.is_absolute():
                        source_path = (service_dir / source_path).resolve()

                    try:
                        path_exists = source_path.exists()
                    except PermissionError:
                        path_exists = True  # Docker daemon has access even if toolkit doesn't
                    if not path_exists:
                        missing_files.append(str(source_path))

            if missing_files:
                logger.error("Missing volume mount sources:")
                for missing in missing_files:
                    logger.error(f"  - {missing}")
                return False

            return True

        except Exception as e:
            logger.warning(f"Volume validation failed: {e}")
            return True  # Don't block on validation errors

    def ensure_network(self, network_name: str) -> None:
        """Ensure that the specified docker network exists."""
        if not network_name:
            return

        try:
            # Check if network exists
            check_cmd = ["docker", "network", "inspect", network_name]
            result = subprocess.run(check_cmd, capture_output=True, check=False)

            if result.returncode != 0:
                logger.info(f"Network '{network_name}' not found. Creating it...")
                create_cmd = ["docker", "network", "create", network_name]
                subprocess.run(create_cmd, check=True, capture_output=True)
                logger.success(f"Network '{network_name}' created successfully")

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to create network '{network_name}': {e}")
            # We don't raise here to allow docker-compose to attempt handling it or fail explicitly

    def _ensure_external_volume(self, volume_name: str) -> None:
        """Ensure that the specified external docker volume exists."""
        try:
            check_cmd = ["docker", "volume", "inspect", volume_name]
            result = subprocess.run(check_cmd, capture_output=True, check=False)

            if result.returncode != 0:
                logger.info(f"External volume '{volume_name}' not found. Creating it...")
                create_cmd = ["docker", "volume", "create", volume_name]
                subprocess.run(create_cmd, check=True, capture_output=True)
                logger.success(f"External volume '{volume_name}' created successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to ensure external volume '{volume_name}': {e.stderr}")
            raise typer.Exit(1) from e

    def _get_compose_config(self, service_dir: Path, environment: str) -> dict[str, Any]:
        """
        Parses and returns the effective Docker Compose configuration for a service.
        """
        full_env = self._get_execution_env(environment)
        cmd = self._get_compose_cmd(service_dir, environment, "config")

        result = subprocess.run(
            cmd,
            cwd=self.settings.project_root,
            env=full_env,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            logger.error(f"Failed to parse compose configuration for {service_dir.name}: {result.stderr}")
            raise typer.Exit(1)

        try:
            return yaml.safe_load(result.stdout)
        except yaml.YAMLError as e:
            logger.error(f"Failed to parse YAML from compose config output for {service_dir.name}: {e}")
            raise typer.Exit(1) from e

    def start_service(self, service_dir: Path, environment: str) -> None:
        """Start Docker Compose service (low-level).

        Args:
            service_dir: Directory containing docker-compose file
            environment: Environment name (dev, staging, prod)

        Raises:
            typer.Exit: If service fails to start
        """
        # Validate volume mounts before starting
        if not self.validate_volume_mounts(service_dir, environment):
            logger.error("Volume mount validation failed. Please fix the missing files before starting.")
            raise typer.Exit(1)

        full_env = self._get_execution_env(environment)

        # Ensure network exists if defined in config
        network_name = full_env.get("NETWORK_NAME")
        if network_name:
            self.ensure_network(network_name)

        # --- NEW: Ensure external volumes exist ---
        try:
            compose_config = self._get_compose_config(service_dir, environment)
            declared_volumes = compose_config.get("volumes", {})
            for vol_name, vol_config in declared_volumes.items():
                if isinstance(vol_config, dict) and vol_config.get("external") is True:
                    self._ensure_external_volume(vol_name)
        except typer.Exit:  # _get_compose_config or _ensure_external_volume can exit on error
            raise
        except Exception as e:
            logger.warning(
                f"Failed to ensure external volumes for {service_dir.name}: {e}. Attempting to start service anyway."
            )
        # --- END NEW ---

        cmd = self._get_compose_cmd(service_dir, environment, DOCKER_CONFIG.COMPOSE_UP)
        cmd.append(DOCKER_CONFIG.FLAG_DETACH)

        # Log command for debugging (hiding secrets in real logs ideally)
        logger.debug(f"Running: {' '.join(cmd)}")

        try:
            subprocess.run(cmd, cwd=self.settings.project_root, env=full_env, check=True)
            logger.success(MESSAGES.SUCCESS_SERVICE_STARTED.format(service_dir.name))
        except subprocess.CalledProcessError as e:
            logger.error(MESSAGES.ERROR_SERVICE_START_FAILED)
            raise typer.Exit(1) from e

    def stop_service(self, service_dir: Path, environment: str, volumes: bool = False) -> None:
        """Stop Docker Compose service (low-level).

        Args:
            service_dir: Directory containing docker-compose file
            environment: Environment name (dev, staging, prod)
            volumes: If True, remove volumes as well
        """
        full_env = self._get_execution_env(environment)
        cmd = self._get_compose_cmd(service_dir, environment, DOCKER_CONFIG.COMPOSE_DOWN)

        if volumes:
            cmd.append("-v")

        try:
            subprocess.run(cmd, cwd=service_dir, env=full_env, check=True)
            logger.success(MESSAGES.SUCCESS_SERVICE_STOPPED.format(service_dir.name))
        except subprocess.CalledProcessError:
            logger.error(MESSAGES.ERROR_SERVICE_STOP_FAILED)

    def build_service(self, service_dir: Path, environment: str, no_cache: bool = False) -> None:
        """Build Docker Compose service (low-level).

        Args:
            service_dir: Directory containing docker-compose file
            environment: Environment name (dev, staging, prod)
            no_cache: If True, build without using cache

        Raises:
            typer.Exit: If build fails
        """
        full_env = self._get_execution_env(environment)
        cmd = self._get_compose_cmd(service_dir, environment, DOCKER_CONFIG.COMPOSE_BUILD)

        if no_cache:
            cmd.append(DOCKER_CONFIG.FLAG_NO_CACHE)

        # Stream output
        try:
            logger.debug(f"Running build command: {' '.join(cmd)}")
            subprocess.run(cmd, cwd=self.settings.project_root, env=full_env, check=True)
            logger.success(MESSAGES.SUCCESS_BUILT.format(service_dir.name))
        except subprocess.CalledProcessError as e:
            logger.error(MESSAGES.ERROR_FAILED.format(f"build {service_dir.name}"))
            logger.error(f"Error details: {e.stderr}")
            raise typer.Exit(1) from e

    def show_logs(self, service_dir: Path, environment: str, follow: bool) -> None:
        """Show Docker Compose logs (low-level).

        Args:
            service_dir: Directory containing docker-compose file
            environment: Environment name (dev, staging, prod)
            follow: If True, follow log output
        """
        full_env = self._get_execution_env(environment)
        cmd = self._get_compose_cmd(service_dir, environment, DOCKER_CONFIG.COMPOSE_LOGS)

        if follow:
            cmd.append(DOCKER_CONFIG.FLAG_FOLLOW)

        try:
            subprocess.run(cmd, cwd=service_dir, env=full_env)
        except KeyboardInterrupt:
            pass  # Handle Ctrl+C gracefully for logs

    # =========================================================================
    # Component-Level Operations (from component_manager.py)
    # =========================================================================

    def start_component(self, component_name: str, environment: str) -> None:
        """Start any component (app, service, or edge).

        Args:
            component_name: Name of the component
            environment: Environment name (dev, staging, prod)

        Raises:
            typer.Exit: If component not found or fails to start
        """
        logger.info(f"Starting {component_name} service")
        component_dir = find_component_directory(component_name)
        if not component_dir:
            logger.error(f"Component not found: {component_name}")
            raise typer.Exit(1)
        self.start_service(component_dir, environment)

    def stop_component(self, component_name: str, environment: str, volumes: bool = False) -> None:
        """Stop any component (app, service, or edge).

        Args:
            component_name: Name of the component
            environment: Environment name (dev, staging, prod)
            volumes: If True, remove volumes as well

        Raises:
            typer.Exit: If component not found
        """
        logger.info(f"Stopping {component_name} service")
        component_dir = find_component_directory(component_name)
        if not component_dir:
            logger.error(f"Component not found: {component_name}")
            raise typer.Exit(1)
        self.stop_service(component_dir, environment, volumes=volumes)

    def show_component_logs(self, component_name: str, environment: str, follow: bool = True) -> None:
        """Show logs for any component (app, service, or edge).

        Args:
            component_name: Name of the component
            environment: Environment name (dev, staging, prod)
            follow: If True, follow log output

        Raises:
            typer.Exit: If component not found
        """
        logger.info(f"Showing logs for {component_name}")
        component_dir = find_component_directory(component_name)
        if not component_dir:
            logger.error(f"Component not found: {component_name}")
            raise typer.Exit(1)
        self.show_logs(component_dir, environment, follow)

    # =========================================================================
    # App-Level Operations (from apps_manager.py)
    # =========================================================================

    def build_app(self, app_name: str, environment: str, no_cache: bool = False) -> None:
        """Build application using docker compose.

        Args:
            app_name: Name of the application
            environment: Environment name (dev, staging, prod)
            no_cache: If True, build without using cache

        Raises:
            FileNotFoundError: If app directory not found
            typer.Exit: If build fails
        """
        component_dir = find_component_directory(app_name)
        if not component_dir:
            logger.error(f"Component not found: {app_name}")
            raise typer.Exit(1)

        try:
            self.build_service(component_dir, environment, no_cache=no_cache)
            logger.success(MESSAGES.SUCCESS_BUILT.format(f"{app_name} ({environment})"))
        except PlatformError as e:
            logger.error(e.message)
            raise typer.Exit(1) from None

    def clean_app(self, app_name: str, environment: str) -> None:
        """Clean application artifacts and resources.

        Args:
            app_name: Name of the application
            environment: Environment name (dev, staging, prod)

        Raises:
            FileNotFoundError: If app directory not found
        """
        logger.info(MESSAGES.INFO_CLEANING.format(app_name))

        component_dir = find_component_directory(app_name)
        if not component_dir:
            logger.error(f"Component not found: {app_name}")
            raise typer.Exit(1)

        self.stop_service(component_dir, environment, volumes=True)
        logger.success(MESSAGES.SUCCESS_CLEANED_RESOURCES.format(app_name))

    def push_app_image(self, app_name: str, environment: str) -> None:
        """Push Docker image for an application to registry.

        Args:
            app_name: Name of the application
            environment: Environment name (dev, staging, prod)

        Raises:
            FileNotFoundError: If app directory not found
        """
        logger.info(MESSAGES.INFO_PUSHING_DOCKER_IMAGE.format(app_name))

        component_dir = find_component_directory(app_name)
        if not component_dir:
            logger.error(f"Component not found: {app_name}")
            raise typer.Exit(1)

        # Load environment variables from YAML+SOPS
        config_manager = ConfigurationManager(environment, self.settings.project_root)
        env_vars = config_manager.get_env_vars()

        registry = env_vars.get("REGISTRY", "docker.io")
        image_name = env_vars.get("IMAGE_NAME", app_name)
        tag = env_vars.get("TAG", environment)
        image_tag = f"{registry}/{image_name}:{tag}"

        command.run_list(["docker", "push", image_tag])
        logger.success(MESSAGES.SUCCESS_DOCKER_IMAGE_PUSHED.format(image_tag))


# Global instance will be lazily initialized
_docker_service_instance: DockerService | None = None


def get_docker_service() -> DockerService:
    """Get or create docker service instance with proper settings.

    Returns:
        DockerService instance with settings loaded
    """
    global _docker_service_instance
    if _docker_service_instance is None:
        from toolkit.config.settings import settings

        _docker_service_instance = DockerService(settings)
    return _docker_service_instance
