"""Ansible server provisioning configuration generator."""

import shutil
from typing import Any

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.core.logging import logger
from toolkit.features import filesystem
from toolkit.features.generator_base import BaseGenerator


class AnsibleGenerator(BaseGenerator):
    """Handles Ansible configuration generation for server provisioning."""

    def generate(self, env: str) -> dict[str, Any]:
        """Generate Ansible configuration.

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and list of generated files
        """
        logger.info(f"Generating Ansible configuration for {env}")

        ansible_dir = self.project_root / PATH_STRUCTURES.INFRA_ANSIBLE
        templates_dir = ansible_dir / "templates"
        roles_dir = ansible_dir / "roles"
        output_dir = ansible_dir / "generated" / env

        if not templates_dir.exists():
            logger.error(f"Ansible templates directory not found: {templates_dir}")
            return {"success": False, "error": "Templates directory not found"}

        try:
            generated_files = []

            # Core configuration files
            config_mappings = [
                ("hosts.template.yml", "hosts.yml"),
                ("ansible.cfg.template", "ansible.cfg"),
                ("group_vars/all.template.yml", "group_vars/all.yml"),
                (f"group_vars/{env}.template.yml", f"group_vars/{env}.yml"),
            ]

            for template_name, output_name in config_mappings:
                template_file = templates_dir / template_name
                output_file = output_dir / output_name

                if template_file.exists():
                    filesystem.ensure_directory(output_file.parent)
                    if self.replace_placeholders(template_file, output_file, env):
                        generated_files.append(str(output_file))
                else:
                    logger.warning(f"Template file not found, skipping: {template_file}")

            # Generate playbooks
            playbook_templates = templates_dir / "playbooks"
            if playbook_templates.exists():
                playbook_output = output_dir / "playbooks"
                filesystem.ensure_directory(playbook_output)

                for template_file in playbook_templates.glob("*.template.yml"):
                    output_file = playbook_output / template_file.name.replace(".template", "")
                    if self.replace_placeholders(template_file, output_file, env):
                        generated_files.append(str(output_file))
            else:
                logger.warning(f"Source playbooks directory not found, skipping: {playbook_templates}")

            # Generate roles
            roles_output = output_dir / "roles"
            if roles_dir.exists():
                if roles_output.exists():
                    shutil.rmtree(roles_output)
                shutil.copytree(roles_dir, roles_output)
                generated_files.append(str(roles_output))
            else:
                logger.warning(f"Source roles directory not found, skipping: {roles_dir}")

            return {"success": True, "files": generated_files}

        except Exception as e:
            logger.error(f"Failed to generate Ansible config: {e}")
            return {"success": False, "error": str(e)}

    def validate(self) -> bool:
        """Validate Ansible configuration and structure.

        Returns:
            True if validation passes, False otherwise
        """
        try:
            # Check if ansible directory exists
            from toolkit.config.settings import settings

            if not settings.ansible_dir.exists():
                logger.error(MESSAGES.ERROR_CONFIG_ANSIBLE_DIR_NOT_FOUND.format(settings.ansible_dir))
                return False

            # Check for basic structure
            basic_files = [
                "templates",
                "templates/playbooks",
                "templates/group_vars",
                "roles",
            ]
            missing_files = [f for f in basic_files if not (settings.ansible_dir / f).exists()]

            # Check for main generated files
            main_files = [
                "generated/staging/ansible.cfg",
                "generated/staging/hosts.yml",
                "generated/staging/group_vars/all.yml",
                "generated/prod/ansible.cfg",
                "generated/prod/hosts.yml",
                "generated/prod/group_vars/all.yml",
            ]
            missing_files += [f for f in main_files if not (settings.ansible_dir / f).exists()]

            if missing_files:
                logger.warning(MESSAGES.WARNING_CONFIG_MISSING_ANSIBLE_FILES.format(", ".join(missing_files)))
                return False

            logger.success(MESSAGES.SUCCESS_CONFIG_ANSIBLE_VALIDATION_PASSED)
            return True
        except Exception:
            return False


# Global instance
ansible_generator = AnsibleGenerator()
