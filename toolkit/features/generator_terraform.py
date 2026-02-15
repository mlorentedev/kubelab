"""Terraform DNS configuration generator."""

from typing import Any

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.core.logging import logger
from toolkit.features import command
from toolkit.features.generator_base import BaseGenerator


class TerraformGenerator(BaseGenerator):
    """Handles Terraform configuration generation for DNS records."""

    def generate(self, env: str) -> dict[str, Any]:
        """Generate Terraform configuration.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and list of generated files
        """
        logger.info(f"Generating Terraform configuration for {env}")

        terraform_dir = self.project_root / PATH_STRUCTURES.INFRA_TERRAFORM
        templates_dir = terraform_dir / "templates"
        output_dir = terraform_dir

        if not templates_dir.exists():
            logger.error(f"Terraform templates directory not found: {templates_dir}")
            return {"success": False, "error": "Templates directory not found"}

        try:
            generated_files = []
            template_files = list(templates_dir.glob("*.tf.template"))

            for template_file in template_files:
                output_file = output_dir / template_file.name.replace(".template", "")

                if self.replace_placeholders(template_file, output_file, env):
                    generated_files.append(str(output_file))
                    logger.info(f"Generated: {output_file}")

            return {"success": True, "files": generated_files}

        except Exception as e:
            logger.error(f"Failed to generate Terraform config: {e}")
            return {"success": False, "error": str(e)}

    def validate(self) -> bool:
        """Validate Terraform setup and configuration.

        Returns:
            True if validation passes, False otherwise
        """
        try:
            # Check if terraform is available
            if command.run("which terraform", check=False).returncode != 0:
                logger.error(MESSAGES.ERROR_TERRAFORM_NOT_FOUND)
                return False

            # Check if terraform directory exists
            from toolkit.config.settings import settings

            if not settings.terraform_dir.exists():
                logger.error(MESSAGES.ERROR_TERRAFORM_DIR_NOT_FOUND.format(settings.terraform_dir))
                return False

            logger.success(MESSAGES.SUCCESS_TERRAFORM_VALID)
            return True
        except Exception:
            return False


# Global instance
terraform_generator = TerraformGenerator()
