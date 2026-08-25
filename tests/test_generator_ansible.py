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
        """Case, whitespace and near-misses are all rejected, not normalised.

        `'BASTION'` and `'mesh '` are the interesting rows: silently accepting
        either would reintroduce the fallback through a different door.
        """
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
        """The pair must be refused before any inventory is emitted."""
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


class TestBothHubsCoexistInTheInventory:
    """GCP-001: `gcp1` joins group `hub` while `aws1` is still reconciling prod.

    The migration is additive-then-subtractive, never a swap: prod's Argo CD
    EndpointSlice is rendered from ONE hub's MagicDNS name, so a simultaneous
    swap would point prod's IngressRoute at a host about to stop existing. Both
    hubs are therefore in the inventory at once, and the thing worth pinning is
    that adding the second did not displace the first.

    The render now names gcp1 (the repoint), and this docstring deliberately no
    longer says which — it cited `Makefile:504` and a provider literal, and both
    halves rotted: the line moved and the hub changed.

    Every expectation derives from `common.yaml`, so these assertions follow the
    SSOT rather than restating it.
    """

    def _hub_hosts(self) -> dict[str, Any]:
        inv = AnsibleGenerator()._build_inventory(_networking())
        return inv["all"]["children"]["hub"]["hosts"]

    def test_the_gcp_hub_is_present(self) -> None:
        net = _networking()
        assert net["gcp"]["hostname"] in self._hub_hosts()

    def test_the_aws_hub_is_gone_because_it_was_RETIRED_not_displaced(self) -> None:
        """This assertion was inverted on 2026-08-24, and the reason matters.

        It used to require `aws1` to still be present, guarding "a swap disguised
        as an addition" during the coexistence window. That window closed:
        GCP-001's AC6 destroyed the machine, and prod reconciles from gcp1. The
        old assertion would now demand a host that does not exist.

        So the invariant is not deleted, it is re-aimed. What must stay true is
        that the AWS hub leaves the inventory by an EXPLICIT retirement in the
        SSOT and never as a side effect of editing the GCP block beside it —
        those two blocks are deliberately duplicated (#1182), which is exactly
        the condition under which a copy-paste displaces its neighbour.
        """
        net = _networking()

        assert net["aws"].get("retired") is True, (
            "aws must be absent because it is declared retired, not because its "
            "address or block was quietly removed"
        )
        assert net["aws"]["hostname"] not in self._hub_hosts()

    def test_the_gcp_hub_is_addressed_by_magicdns(self) -> None:
        """A MIG recreates on every preemption and the Tailscale IP rotates with
        it, so an inventory pinned to an address needs regenerating each time."""
        net = _networking()
        entry = self._hub_hosts()[net["gcp"]["hostname"]]
        assert entry["ansible_host"] == net["gcp"]["tailscale_dns"]

    def test_the_gcp_hub_did_not_fall_through_to_the_homelab_ssh_user(self) -> None:
        """SSOT-014a infers the SSH-user category from YAML POSITION.

        `networking.gcp` is a top-level sibling like `vps` and `aws`, not an
        entry under `nodes`, and the generator has to place it in the `cloud`
        category explicitly. Getting this wrong yields `manu` instead of
        `deployer` — an inventory that looks right and cannot authenticate.
        """
        net = _networking()
        entry = self._hub_hosts()[net["gcp"]["hostname"]]
        assert entry["ansible_user"] == net["ssh_users"]["cloud"]
        assert entry["ansible_user"] != net["ssh_users"]["homelab"]


class TestRetiredCloudNodes:
    """A declaration that is a rebuild recipe must not become an inventory host.

    GCP-001's AC6 destroyed `aws1` and #1333 kept `networking.aws` on purpose,
    because `infra/terraform/aws/` and `provision-aws1.yml` restore it in one
    command and read those values. Nothing distinguished the two, so every
    consumer that enumerates nodes kept enumerating a machine that does not
    exist — `make test-infra` found it as six SSH timeouts (#1365).
    """

    def test_a_retired_cloud_node_produces_no_host(self) -> None:
        net = _networking()
        assert net["aws"].get("retired") is True, "the SSOT should still mark aws as retired"

        hosts = _hosts(AnsibleGenerator()._build_inventory(net))

        assert not [h for h in hosts if "aws" in h], f"a retired node reached the inventory: {sorted(hosts)}"

    def test_it_keeps_the_address_that_makes_restoration_one_flag(self) -> None:
        """`retired` is checked BEFORE the address, never instead of it.

        Deleting `tailscale_dns` would also remove the node from the inventory,
        and would make bringing AWS back a reconstruction rather than a flag.
        """
        aws = _networking()["aws"]

        assert aws.get("tailscale_dns") or aws.get("tailscale_ip")

    def test_clearing_the_flag_brings_the_host_back(self) -> None:
        net = _networking()
        net["aws"] = {**net["aws"], "retired": False}

        hosts = _hosts(AnsibleGenerator()._build_inventory(net))

        assert [h for h in hosts if "aws" in h], "un-retiring must restore the host, or the flag is a one-way door"

    def test_the_live_hub_is_not_retired(self) -> None:
        """Guards the copy-paste: the two cloud blocks are deliberately duplicated
        (#1182), so a flag added to one is one edit away from landing on the other."""
        net = _networking()
        assert not net["gcp"].get("retired")

        hosts = _hosts(AnsibleGenerator()._build_inventory(net))

        assert [h for h in hosts if "gcp" in h], "the running hub must still be in the inventory"
