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

# VPS node — IP from networking.vps.tailscale_ip in common.yaml
VPS_NODE = NodeInfo(
    name="vps",
    host=_COMMON["networking"]["vps"]["tailscale_ip"],
    group="vps",
)


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


def ssh_run(
    host: str,
    command: str,
    timeout: int = 10,
    user: str = "manu",
) -> subprocess.CompletedProcess[str]:
    """Run a command over SSH and return the result."""
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
