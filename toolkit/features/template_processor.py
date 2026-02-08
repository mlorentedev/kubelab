"""Template processing utilities to replace replace-placeholders.sh."""

from pathlib import Path

from toolkit.config.settings import settings
from toolkit.core.logging import logger
from toolkit.features.configuration import ConfigurationManager


class TemplateProcessor:
    """Processor for template files with placeholder replacement."""

    def __init__(self) -> None:
        """Initialize the template processor."""
        self.project_root = settings.project_root

    # Removed escape_for_replacement() - never called, archived in Phase 4

    def replace_placeholders(
        self,
        template_path: Path,
        output_path: Path,
        env: str | None = None,
    ) -> bool:
        """Replace placeholders in a template file with environment variables.

        Args:
            template_path: Path to the template file
            output_path: Path where the processed file will be written
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

    # Removed 3 unused methods - archived in Phase 4 (docs/REFACTORING-AUDIT.md):
    # - process_templates_in_directory() - batch processing not needed
    # - get_template_variables() - template validation not integrated
    # - validate_template_variables() - template validation not integrated


# Global template processor instance
template_processor = TemplateProcessor()
