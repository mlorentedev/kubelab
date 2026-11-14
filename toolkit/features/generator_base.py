"""Base generator class and shared template processing utilities."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from toolkit.config.settings import PROJECT_ROOT, settings
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.product_registry import platform_apps


class BaseGenerator(ABC):
    """Abstract base class for configuration generators."""

    def __init__(self) -> None:
        """Initialize the generator."""
        self.project_root = PROJECT_ROOT  # what settings.project_root resolves to, without building settings

    @abstractmethod
    def generate(self, env: str) -> dict[str, Any]:
        """Generate configuration for the specified environment.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and generated files
        """
        pass

    def replace_placeholders(
        self,
        template_path: Path,
        output_path: Path,
        env: str | None = None,
    ) -> bool:
        """Replace placeholders in a template file with environment variables.

        Args:
            template_path: Path to template file
            output_path: Path to output file
            env: Environment name (dev, staging, prod). Defaults to settings.environment

        Returns:
            True if successful, False otherwise
        """
        if not template_path.exists():
            logger.error(f"Template not found: {template_path}")
            return False

        # Load environment variables from YAML+SOPS
        if env is None:
            env = settings.environment

        config_manager = ConfigurationManager(env, self.project_root)
        env_vars = config_manager.get_env_vars()

        try:
            # Read template file
            with open(template_path, encoding="utf-8") as f:
                content = f.read()

            # Replace placeholders with environment variables
            for var_name, var_value in env_vars.items():
                if var_value:
                    placeholder = "{{ " + var_name + " }}"
                    content = content.replace(placeholder, str(var_value))

            # Write output file
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)

            return True

        except Exception as e:
            logger.error(f"Failed to process template {template_path}: {e}")
            return False

    @staticmethod
    def pinned_platform_apps(env_vars: dict[str, str], env: str) -> dict[str, str]:
        """The registered platform apps that have a ``version`` in ``env``, with that version.

        No pin means the app is not deployed in that env, so no generator emits anything for
        it: not a Deployment, and not a route or an access rule that would point at one that
        does not exist. The fallback to ``latest`` this replaces put a registered app on a
        mutable tag in every overlay, prod included (#3456, ADR-046 defect #1). The skip is a
        warning, never silent.
        """
        pinned: dict[str, str] = {}
        for component in platform_apps():
            version = env_vars.get(f"APPS_PLATFORM_{component.upper().replace('-', '_')}_VERSION")
            if version:
                pinned[component] = str(version)
            else:
                logger.warning(f"Skipping {component} in {env}: apps.platform.{component}.version is not set")
        return pinned
