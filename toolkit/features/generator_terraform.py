"""Terraform DNS configuration generator."""

import json
from typing import Any

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.core.logging import logger
from toolkit.features import command
from toolkit.features.generator_base import BaseGenerator


class TerraformGenerator(BaseGenerator):
    """Validates Terraform DNS configuration before running commands."""

    def generate(self, env: str) -> dict[str, Any]:
        """Validate that Terraform DNS directory and services.json exist.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status
        """
        logger.info(f"Validating Terraform configuration for {env}")

        terraform_dir = self.project_root / PATH_STRUCTURES.INFRA_TERRAFORM

        if not terraform_dir.exists():
            logger.error(f"Terraform directory not found: {terraform_dir}")
            return {"success": False, "error": "Terraform directory not found"}

        services_file = terraform_dir / "services.json"
        if not services_file.exists():
            logger.error(f"services.json not found: {services_file}")
            return {"success": False, "error": "services.json not found"}

        try:
            with open(services_file) as f:
                services = json.load(f)
            if not isinstance(services, list) or len(services) == 0:
                logger.error("services.json must be a non-empty JSON array")
                return {"success": False, "error": "Invalid services.json"}
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to parse services.json: {e}")
            return {"success": False, "error": str(e)}

        main_tf = terraform_dir / "main.tf"
        if not main_tf.exists():
            logger.error(f"main.tf not found: {main_tf}")
            return {"success": False, "error": "main.tf not found"}

        tfvars = terraform_dir / f"{env}.tfvars"
        if not tfvars.exists():
            logger.warning(f"No tfvars file for {env}: {tfvars}")

        env_services = [s for s in services if env in s.get("environments", [])]
        logger.info(f"Found {len(env_services)} services for {env} environment")
        logger.success(f"Terraform configuration valid for {env}")

        return {"success": True, "services_count": len(env_services)}

    def validate(self) -> bool:
        """Validate Terraform setup and configuration.

        Returns:
            True if validation passes, False otherwise
        """
        try:
            if command.run("which terraform", check=False).returncode != 0:
                logger.error(MESSAGES.ERROR_TERRAFORM_NOT_FOUND)
                return False

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
