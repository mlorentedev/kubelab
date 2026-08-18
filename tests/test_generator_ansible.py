"""Tests for AnsibleGenerator inventory transport (TOOL-016 / #818).

Backfills the previously-absent AnsibleGenerator unit coverage. Reads the real
networking SSOT from common.yaml (never hardcodes IPs, per the repo rule) and
derives every expected value from that same source, so the assertions cannot drift.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.generator_ansible import VALID_TRANSPORTS, AnsibleGenerator

_COMMON = Path(__file__).resolve().parents[1] / "infra" / "config" / "values" / "common.yaml"


def _networking() -> dict[str, Any]:
    return yaml.safe_load(_COMMON.read_text(encoding="utf-8"))["networking"]


def _hosts(inventory: dict[str, Any]) -> dict[str, Any]:
    """Flatten inventory children groups -> {hostname: host_vars}."""
    out: dict[str, Any] = {}
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


class TestTransportValidation:
    """`transport` must be rejected at the feature layer, not only in the CLI (#1135).

    Validation used to live solely in `toolkit/cli/infra.py`. `_build_inventory`
    branched on `transport == "bastion"` and let everything else fall through to
    mesh, so a programmatic caller passing `'lan'` or a typo got a working-looking
    inventory with no ProxyCommand — indistinguishable from a correct mesh run,
    which is the property that makes a silent fallback worse than a crash.
    """

    @pytest.mark.parametrize("bogus", ["lan", "bastio", "BASTION", "", "mesh "])
    def test_unknown_transport_raises(self, bogus: str) -> None:
        with pytest.raises(ValueError, match="unknown transport"):
            AnsibleGenerator()._build_inventory(_networking(), transport=bogus)

    @pytest.mark.parametrize("valid", VALID_TRANSPORTS)
    def test_declared_transports_are_accepted(self, valid: str) -> None:
        """The negative side: a guard that rejected everything would pass the test above."""
        inv = AnsibleGenerator()._build_inventory(_networking(), transport=valid)
        assert _hosts(inv), f"transport={valid!r} produced an empty inventory"

    def test_silent_mesh_fallback_is_gone(self) -> None:
        """The regression in its original shape: bogus transport must not equal mesh output."""
        mesh = AnsibleGenerator()._build_inventory(_networking(), transport="mesh")
        with pytest.raises(ValueError):
            bogus = AnsibleGenerator()._build_inventory(_networking(), transport="bogus")
            assert bogus != mesh, "bogus transport silently produced the mesh inventory"


class TestBootstrapBastionCombination:
    """bootstrap + bastion is contradictory and must be refused (#1135).

    bootstrap addresses homelab nodes by `lan_ip` (172.16.1.x); bastion attaches a
    ProxyCommand through the VPS to every node without a `public_ip`. Together they
    emit homelab hosts reachable only via a jump with no route to that LAN. Since
    bootstrap affects *only* homelab nodes, the combination has no residual use.
    """

    def test_bootstrap_with_bastion_raises(self) -> None:
        with pytest.raises(ValueError, match="contradictory"):
            AnsibleGenerator()._build_inventory(_networking(), bootstrap=True, transport="bastion")

    def test_each_alone_still_works(self) -> None:
        """Both halves must survive on their own — the guard is about the pair."""
        boot = AnsibleGenerator()._build_inventory(_networking(), bootstrap=True, transport="mesh")
        bast = AnsibleGenerator()._build_inventory(_networking(), bootstrap=False, transport="bastion")
        assert _hosts(boot), "bootstrap alone produced an empty inventory"
        assert any("ansible_ssh_common_args" in hv for hv in _hosts(bast).values()), (
            "bastion alone emitted no ProxyCommand — the guard broke the feature"
        )

    def test_bootstrap_alone_uses_lan_ips(self) -> None:
        """Anchors why the pair is contradictory, from the SSOT rather than a literal."""
        net = _networking()
        inv = AnsibleGenerator()._build_inventory(net, bootstrap=True, transport="mesh")
        hosts = _hosts(inv)
        lan_ips = {n["lan_ip"] for n in net.get("nodes", {}).values() if n.get("lan_ip")}
        used = {hv["ansible_host"] for hv in hosts.values()}
        assert used & lan_ips, "bootstrap did not address any node by its lan_ip"
