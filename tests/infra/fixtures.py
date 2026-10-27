"""Infrastructure test fixtures — SSH helpers, node discovery, connectivity checks."""

from __future__ import annotations

import os
import shutil
import subprocess
from collections.abc import Callable
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
    # SSOT-014a: per-node override wins, else category SSOT (cloud for VPS).
    vars={"ansible_user": _COMMON["networking"]["vps"].get("ssh_user") or _COMMON["networking"]["ssh_users"]["cloud"]},
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


#: The cloud blocks the inventory generator lets `retired` remove, besides `nodes.*`.
#: A flag anywhere else removes nothing from the generated inventory, so it must
#: not remove anything from the suite either (test_infra_inventory_retired.py).
RETIRABLE_CLOUD_BLOCKS = ("aws", "gcp")


def retired_addresses(networking: dict) -> frozenset[str]:
    """Every address of a node declared `retired`: a rebuild recipe, not a machine.

    The inventory names hosts its own way (`kubelab-jet1` for
    `networking.nodes.jetson`), so the address is what links it to the declaration.
    `tailscale_dns` counts as one: it is the `ansible_host` the generator gives a hub.
    """
    blocks = [*networking.get("nodes", {}).values(), *(networking.get(key) for key in RETIRABLE_CLOUD_BLOCKS)]
    return frozenset(
        block[attr]
        for block in blocks
        if block and block.get("retired")
        for attr in ("tailscale_ip", "tailscale_dns", "lan_ip", "public_ip")
        if block.get(attr)
    )


def load_inventory(
    inventory_path: Path | None = None,
    networking: dict | None = None,
) -> list[NodeInfo]:
    """Parse the Ansible inventory YAML and return its nodes, less the retired ones."""
    if inventory_path is None:
        inventory_path = _REPO_ROOT / "infra" / "ansible" / "inventories" / "homelab.yml"

    if not inventory_path.exists():
        return []

    with open(inventory_path) as f:
        data = yaml.safe_load(f)

    retired = retired_addresses(_COMMON["networking"] if networking is None else networking)
    nodes: list[NodeInfo] = []
    children = data.get("all", {}).get("children", {})
    for group_name, group_data in children.items():
        hosts = group_data.get("hosts", {})
        for hostname, host_vars in hosts.items():
            if host_vars is None:
                host_vars = {}
            if host_vars.get("ansible_host", hostname) in retired:
                continue
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
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=5",
            "-o",
            "BatchMode=yes",
            f"{user}@{host}",
            command,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


#: Where the macOS app keeps its CLI. It puts nothing on PATH, so without this
#: every infra test skipped on the Mac as "VPN not connected" (#2283).
MACOS_TAILSCALE_CLI = Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale")


def tailscale_cli(which: Callable[[str], str | None] = shutil.which, bundle: Path = MACOS_TAILSCALE_CLI) -> str | None:
    """The Tailscale CLI to run: the one on PATH, else the macOS app's, else None.

    The bundle counts only when it can be executed, as `which` requires of a PATH entry.
    """
    return which("tailscale") or (str(bundle) if bundle.is_file() and os.access(bundle, os.X_OK) else None)


def vpn_unavailable() -> str | None:
    """Why this machine cannot reach the tailnet, or None when it can.

    An absent CLI and a disconnected tailnet are told apart, because the fix for
    each is different and a skip reason that conflates them hides the first.
    """
    cli = tailscale_cli()
    if cli is None:
        if MACOS_TAILSCALE_CLI.is_file():
            # Installed, but without its execute bit (an archive extracted without
            # modes, a broken update): the fix is chmod, not an install.
            return f"Tailscale CLI cannot run: {MACOS_TAILSCALE_CLI} is not executable"
        return f"Tailscale CLI not found: not on PATH, and no {MACOS_TAILSCALE_CLI}"
    try:
        result = subprocess.run([cli, "status", "--json"], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        return f"Tailscale not connected: `{cli} status` timed out"
    except OSError as exc:
        # Found but not runnable (removed since, or a broken install): a CLI problem, not a down tailnet.
        return f"Tailscale CLI cannot run: {exc}"
    if result.returncode != 0:
        return f"Tailscale not connected: `{cli} status` exited {result.returncode}"
    return None


def tailscale_connected() -> bool:
    """Check if the local machine has Tailscale running and connected."""
    return vpn_unavailable() is None
