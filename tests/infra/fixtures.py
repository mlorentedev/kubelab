"""Infrastructure test fixtures — SSH helpers, node discovery, connectivity checks."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class NodeInfo:
    """A node from the Ansible inventory."""

    name: str
    host: str
    group: str
    vars: dict[str, str] = field(default_factory=dict)


def _load_common_config() -> dict:
    """Load common.yaml for networking values (VPS IP, Tailscale CIDR, etc.)."""
    config_path = _REPO_ROOT / "infra" / "config" / "values" / "common.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


_COMMON = _load_common_config()

# VPS node — Tailscale IP from SSOT (SSH access via VPN)
VPS_NODE = NodeInfo(
    name="vps",
    host=_COMMON["networking"]["vps"]["tailscale_ip"],
    group="vps",
    vars={"ansible_user": _COMMON["networking"]["vps"].get("ssh_user", "deployer")},
)

# Default SSH user from Ansible inventory global vars (SSOT)
_DEFAULT_SSH_USER: str = "manu"  # populated by load_inventory()


def _init_default_ssh_user() -> None:
    """Read the global ansible_user from inventory (SSOT)."""
    global _DEFAULT_SSH_USER
    inventory_path = _REPO_ROOT / "infra" / "ansible" / "inventories" / "homelab.yml"
    if not inventory_path.exists():
        return
    try:
        with open(inventory_path) as f:
            data = yaml.safe_load(f)
        if data is None:
            return
        _DEFAULT_SSH_USER = data.get("all", {}).get("vars", {}).get("ansible_user", "manu")
    except (yaml.YAMLError, OSError) as e:
        import warnings

        warnings.warn(f"Failed to read ansible_user from {inventory_path}: {e}", stacklevel=2)


_init_default_ssh_user()


def ssh_host(node: NodeInfo) -> str:
    """SSH host for a node — always ansible_host (Tailscale IP, access via VPN)."""
    return node.host


def ssh_user(node: NodeInfo) -> str:
    """SSH user for a node — per-node override or inventory global default."""
    return node.vars.get("ansible_user", _DEFAULT_SSH_USER)


def load_inventory(
    inventory_path: Path | None = None,
) -> list[NodeInfo]:
    """Parse the Ansible inventory YAML and return a list of NodeInfo."""
    if inventory_path is None:
        inventory_path = (
            _REPO_ROOT / "infra" / "ansible" / "inventories" / "homelab.yml"
        )

    if not inventory_path.exists():
        return []

    with open(inventory_path) as f:
        data = yaml.safe_load(f)

    nodes: list[NodeInfo] = []
    children = data.get("all", {}).get("children", {})
    for group_name, group_data in children.items():
        hosts = group_data.get("hosts", {})
        for hostname, host_vars in hosts.items():
            if host_vars is None:
                host_vars = {}
            nodes.append(
                NodeInfo(
                    name=hostname,
                    host=host_vars.get("ansible_host", hostname),
                    group=group_name,
                    vars=host_vars,
                )
            )
    return nodes


def node_ssh_run(
    node: NodeInfo,
    command: str,
    timeout: int = 10,
) -> subprocess.CompletedProcess[str]:
    """Run a command over SSH using the node's SSOT user and host."""
    user = ssh_user(node)
    host = ssh_host(node)
    return subprocess.run(
        [
            "ssh",
            "-o", "StrictHostKeyChecking=no",
            "-o", "ConnectTimeout=5",
            "-o", "BatchMode=yes",
            f"{user}@{host}",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def tailscale_connected() -> bool:
    """Check if the local machine has Tailscale running and connected."""
    try:
        result = subprocess.run(
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
