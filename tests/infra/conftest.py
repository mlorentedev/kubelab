"""Infrastructure test conftest — shared fixtures for infra tests."""

from __future__ import annotations

import pytest

from .fixtures import VPS_NODE, NodeInfo, load_inventory, tailscale_connected


@pytest.fixture(scope="session")
def require_vpn() -> None:
    """Skip all infra tests if Tailscale is not connected."""
    if not tailscale_connected():
        pytest.skip("Tailscale VPN not connected — infra tests require VPN access")


@pytest.fixture(scope="session")
def inventory(require_vpn: None) -> list[NodeInfo]:
    """All nodes from the Ansible inventory."""
    nodes = load_inventory()
    if not nodes:
        pytest.skip("No nodes found in Ansible inventory")
    return nodes


@pytest.fixture(scope="session")
def lan_nodes(inventory: list[NodeInfo]) -> list[NodeInfo]:
    """LAN nodes only (mini PCs, K3s VMs)."""
    return [n for n in inventory if n.group == "lan_nodes"]


@pytest.fixture(scope="session")
def gateway_nodes(inventory: list[NodeInfo]) -> list[NodeInfo]:
    """Gateway nodes only (RPi4, RPi3)."""
    return [n for n in inventory if n.group == "gateway_nodes"]


@pytest.fixture(scope="session")
def vps_node(require_vpn: None) -> NodeInfo:
    """VPS node for production tests."""
    return VPS_NODE
