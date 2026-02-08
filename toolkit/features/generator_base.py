"""Base generator class and shared template processing utilities."""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager


class BaseGenerator(ABC):
    """Abstract base class for configuration generators."""

    def __init__(self) -> None:
        """Initialize the generator."""
        self.project_root = settings.project_root

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
