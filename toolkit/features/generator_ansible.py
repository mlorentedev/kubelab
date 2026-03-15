"""Ansible configuration generator — produces inventory from SSOT (common.yaml)."""

from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from toolkit.config.constants import MESSAGES, PATH_STRUCTURES
from toolkit.core.logging import logger
from toolkit.features import filesystem
from toolkit.features.configuration import ConfigurationManager
from toolkit.features.generator_base import BaseGenerator


class AnsibleGenerator(BaseGenerator):
    """Generates Ansible inventory from common.yaml (SSOT).

    Playbooks load config directly via include_vars (ADR-020 Rev2).
    This generator only produces the dynamic inventory (hosts.yml).
    """

    def generate(self, env: str) -> dict[str, Any]:
        """Generate Ansible inventory from SSOT config.

        Reads networking.* from common.yaml and produces:
        - hosts.yml: dynamic inventory with host groups

        Args:
            env: Environment name (dev, staging, prod)

        Returns:
            Dictionary with success status and list of generated files
        """
        logger.info(f"Generating Ansible inventory for {env}")

        ansible_dir = self.project_root / PATH_STRUCTURES.INFRA_ANSIBLE
        output_dir = ansible_dir / "generated" / env
        filesystem.ensure_directory(output_dir)

        try:
            config_manager = ConfigurationManager(env, self.project_root)
            config = config_manager.get_merged_config()
            networking = config.get("networking", {})

            generated_files = []

            # Generate inventory
            inventory_path = output_dir / "hosts.yml"
            self._generate_inventory(networking, inventory_path)
            generated_files.append(str(inventory_path))

            logger.success(f"Generated {len(generated_files)} Ansible files for {env}")
            return {"success": True, "files": generated_files}

        except Exception as e:
            logger.error(f"Failed to generate Ansible config: {e}")
            return {"success": False, "error": str(e)}

    def _generate_inventory(self, networking: dict[str, Any], output_path: Path) -> None:
        """Generate Ansible inventory YAML from networking config."""
        vps = networking.get("vps", {})
        nodes = networking.get("nodes", {})
        ssh_key = networking.get("ssh_key", "~/.ssh/id_ed25519")

        # Collect all nodes (VPS + homelab nodes)
        all_nodes: list[dict[str, Any]] = []

        # VPS
        if vps:
            all_nodes.append(
                {
                    "hostname": vps.get("hostname", "kubelab-vps"),
                    "ansible_host": vps.get("tailscale_ip"),
                    "ansible_user": vps.get("ssh_user", "deployer"),
                    "public_ip": vps.get("public_ip"),
                    "groups": vps.get("ansible_groups", []),
                }
            )

        # Homelab nodes
        for _node_key, node in nodes.items():
            entry: dict[str, Any] = {
                "hostname": node.get("hostname", _node_key),
                "ansible_host": node.get("tailscale_ip"),
                "ansible_user": node.get("ssh_user", "manu"),
                "groups": node.get("ansible_groups", []),
            }
            if node.get("lan_ip"):
                entry["lan_ip"] = node["lan_ip"]
            if node.get("legacy_python"):
                entry["legacy_python"] = True
            all_nodes.append(entry)

        # Build group → hosts mapping
        groups: dict[str, list[str]] = defaultdict(list)
        host_vars: dict[str, dict[str, Any]] = {}

        for node in all_nodes:
            hostname = node["hostname"]
            host_vars[hostname] = {
                "ansible_host": node["ansible_host"],
                "ansible_user": node["ansible_user"],
            }
            if node.get("public_ip"):
                host_vars[hostname]["public_ip"] = node["public_ip"]
            if node.get("lan_ip"):
                host_vars[hostname]["lan_ip"] = node["lan_ip"]
            if node.get("legacy_python"):
                host_vars[hostname]["legacy_python"] = True

            for group in node.get("groups", []):
                groups[group].append(hostname)

        # Build inventory structure
        inventory: dict[str, Any] = {
            "all": {
                "vars": {
                    "ansible_ssh_private_key_file": ssh_key,
                    "ansible_ssh_common_args": "-o StrictHostKeyChecking=no",
                    "ansible_python_interpreter": "/usr/bin/python3",
                },
                "children": {},
            }
        }

        for group_name, hostnames in sorted(groups.items()):
            group_hosts: dict[str, Any] = {}
            for hostname in hostnames:
                group_hosts[hostname] = host_vars[hostname]
            inventory["all"]["children"][group_name] = {"hosts": group_hosts}

        # Write YAML
        header = (
            "# Generated by toolkit — DO NOT EDIT\n"
            "# Source: infra/config/values/common.yaml (networking.*)\n"
            "# Regenerate: toolkit infra ansible generate --env {env}\n"
            "---\n"
        )
        output_path.write_text(header + yaml.dump(inventory, default_flow_style=False, sort_keys=False))
        logger.info(f"  Inventory: {output_path} ({len(all_nodes)} hosts, {len(groups)} groups)")

    def validate(self) -> bool:
        """Validate Ansible configuration and structure."""
        try:
            from toolkit.config.settings import settings

            if not settings.ansible_dir.exists():
                logger.error(MESSAGES.ERROR_CONFIG_ANSIBLE_DIR_NOT_FOUND.format(settings.ansible_dir))
                return False

            required_dirs = ["roles", "playbooks", "inventories"]
            missing = [d for d in required_dirs if not (settings.ansible_dir / d).exists()]

            if missing:
                logger.warning(MESSAGES.WARNING_CONFIG_MISSING_ANSIBLE_FILES.format(", ".join(missing)))
                return False

            logger.success(MESSAGES.SUCCESS_CONFIG_ANSIBLE_VALIDATION_PASSED)
            return True
        except Exception:
            return False


# Global instance
ansible_generator = AnsibleGenerator()
