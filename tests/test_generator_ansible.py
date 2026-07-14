"""Tests for AnsibleGenerator inventory transport (TOOL-016 / #818).

Backfills the previously-absent AnsibleGenerator unit coverage. Reads the real
networking SSOT from common.yaml (never hardcodes IPs, per the repo rule) and
derives every expected value from that same source, so the assertions cannot drift.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from toolkit.features.generator_ansible import AnsibleGenerator

_COMMON = Path(__file__).resolve().parents[1] / "infra" / "config" / "values" / "common.yaml"


def _networking() -> dict:
    return yaml.safe_load(_COMMON.read_text(encoding="utf-8"))["networking"]


def _hosts(inventory: dict) -> dict:
    """Flatten inventory children groups -> {hostname: host_vars}."""
    out: dict = {}
    for group in inventory["all"]["children"].values():
        out.update(group.get("hosts", {}))
    return out


class TestMeshTransportRegression:
    """Default / mesh transport must reproduce today's inventory shape (no regression)."""

    def test_no_per_host_proxy_in_mesh(self) -> None:
        inv = AnsibleGenerator()._build_inventory(_networking(), transport="mesh")
        for name, hv in _hosts(inv).items():
            assert "ansible_ssh_common_args" not in hv, f"{name} has per-host ssh args in mesh mode"

    def test_global_ssh_args_unchanged(self) -> None:
        inv = AnsibleGenerator()._build_inventory(_networking(), transport="mesh")
        assert inv["all"]["vars"]["ansible_ssh_common_args"] == "-o StrictHostKeyChecking=accept-new"

    def test_mesh_is_the_default(self) -> None:
        net = _networking()
        assert AnsibleGenerator()._build_inventory(net) == AnsibleGenerator()._build_inventory(net, transport="mesh")


class TestBastionTransport:
    """Bastion transport proxies mesh-only nodes through the VPS, never the VPS itself."""

    def test_mesh_only_nodes_get_proxy_via_ssot_bastion(self) -> None:
        net = _networking()
        vps = net["vps"]
        bastion_ip = vps["public_ip"]
        bastion_user = net["ssh_users"]["cloud"]
        vps_host = vps.get("hostname", "kubelab-vps")

        hosts = _hosts(AnsibleGenerator()._build_inventory(net, transport="bastion"))

        # VPS is the jump — never proxied through itself.
        assert "ansible_ssh_common_args" not in hosts[vps_host]

        # Every other (mesh-only) host carries a ProxyCommand to the SSOT bastion,
        # authenticating the hop with the SSOT ssh_key.
        mesh_only = [h for h in hosts if h != vps_host]
        assert mesh_only, "fixture should have >=1 mesh-only node"
        for name in mesh_only:
            args = hosts[name].get("ansible_ssh_common_args", "")
            assert "ProxyCommand" in args, f"{name} missing ProxyCommand"
            assert f"{bastion_user}@{bastion_ip}" in args, f"{name} proxy not pointed at the SSOT bastion"
            assert net["ssh_key"] in args, f"{name} proxy must use the SSOT ssh_key for the hop"

    def test_bastion_requires_a_public_jump_fail_closed(self) -> None:
        """No VPS public_ip -> no reachable jump -> fail closed (never a tailscale-only jump)."""
        net = _networking()
        net = {**net, "vps": {k: v for k, v in net["vps"].items() if k != "public_ip"}}
        with pytest.raises(ValueError):
            AnsibleGenerator()._build_inventory(net, transport="bastion")
