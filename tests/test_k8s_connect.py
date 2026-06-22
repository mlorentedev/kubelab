"""Tests for the cluster-access transport feature (ADR-052 Phase 2 / TOOL-014).

Cover the pure helpers — transport resolution from the SSOT, ts-bridge argv,
binary discovery, and transport-state (de)serialization — without any network.
The process spawn / port probe / kill live in connect/disconnect/status, which
are not exercised here (they need a live mesh).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from toolkit.features import k8s_connect as tc
from toolkit.features.k8s_connect import (
    ClusterTransport,
    TransportState,
    locate_ts_bridge,
    resolve_transport,
    statefile_path,
    ts_bridge_argv,
)

# A fixture common.yaml exercising all three node positions:
#   - homelab node under networking.nodes.* (ace1)
#   - cloud vps at networking.vps (has a public_ip -> "public" transport)
#   - cloud aws at networking.aws (mesh-only)
_COMMON = """\
clusters:
  staging:
    node: ace1
    ssh_alias: ace1
    local_port: 16443
  prod:
    node: vps
    ssh_alias: vps
    local_port: 16444
  hub:
    node: aws1
    ssh_alias: aws1
    local_port: 16445
networking:
  vps:
    hostname: kubelab-vps
    public_ip: 162.55.57.175
    tailscale_ip: 100.64.0.2
  aws:
    hostname: aws1
    tailscale_ip: 100.64.0.7
  nodes:
    ace1:
      hostname: ace1
      tailscale_ip: 100.64.0.11
      lan_ip: 172.16.1.2
"""


@pytest.fixture
def common_yaml(tmp_path: Path) -> Path:
    p = tmp_path / "common.yaml"
    p.write_text(_COMMON)
    return p


class TestResolveTransport:
    """ADR-052 D3: prod -> public endpoint (direct); staging/hub -> ts-bridge mesh."""

    def test_staging_resolves_to_ts_bridge_over_the_mesh(self, common_yaml: Path) -> None:
        t = resolve_transport("staging", common_yaml)
        assert t == ClusterTransport(
            env="staging", kind="ts-bridge", target_host="100.64.0.11", apiserver_port=6443, local_port=16443
        )

    def test_prod_resolves_to_the_public_endpoint_no_tunnel(self, common_yaml: Path) -> None:
        t = resolve_transport("prod", common_yaml)
        assert t.kind == "public"
        assert t.target_host == "162.55.57.175"  # networking.vps.public_ip
        assert t.local_port == 16444

    def test_hub_resolves_to_ts_bridge_at_the_aws_mesh_address(self, common_yaml: Path) -> None:
        t = resolve_transport("hub", common_yaml)
        assert t.kind == "ts-bridge"
        assert t.target_host == "100.64.0.7"  # networking.aws.tailscale_ip
        assert t.local_port == 16445

    def test_apiserver_port_defaults_to_6443(self, common_yaml: Path) -> None:
        assert resolve_transport("hub", common_yaml).apiserver_port == 6443

    def test_apiserver_port_override_is_honored(self, tmp_path: Path) -> None:
        p = tmp_path / "common.yaml"
        p.write_text(
            "clusters:\n  staging:\n    node: ace1\n    ssh_alias: ace1\n    local_port: 16443\n"
            "    apiserver_port: 7443\n"
            "networking:\n  nodes:\n    ace1:\n      tailscale_ip: 100.64.0.11\n"
        )
        assert resolve_transport("staging", p).apiserver_port == 7443

    def test_no_hardcoded_ips_target_comes_from_the_ssot(self, tmp_path: Path) -> None:
        # Move ace1 to a different mesh IP; the resolver must follow the SSOT.
        p = tmp_path / "common.yaml"
        p.write_text(
            "clusters:\n  staging:\n    node: ace1\n    ssh_alias: ace1\n    local_port: 16443\n"
            "networking:\n  nodes:\n    ace1:\n      tailscale_ip: 100.64.0.99\n"
        )
        assert resolve_transport("staging", p).target_host == "100.64.0.99"

    def test_unknown_cluster_lists_valid_names(self, common_yaml: Path) -> None:
        with pytest.raises(KeyError, match="hub, prod, staging"):
            resolve_transport("dev", common_yaml)

    def test_node_absent_from_networking_raises_clearly(self, tmp_path: Path) -> None:
        p = tmp_path / "common.yaml"
        p.write_text(
            "clusters:\n  staging:\n    node: ghost\n    ssh_alias: ghost\n    local_port: 16443\n"
            "networking:\n  nodes: {}\n"
        )
        with pytest.raises(KeyError, match="ghost"):
            resolve_transport("staging", p)


class TestTsBridgeArgv:
    def test_builds_a_manual_mode_target_and_local_bind(self) -> None:
        t = ClusterTransport("staging", "ts-bridge", "100.64.0.11", 6443, 16443)
        argv = ts_bridge_argv("/opt/ts-bridge", t)
        assert argv == [
            "/opt/ts-bridge",
            "connect",
            "--manual-mode",
            "--target",
            "100.64.0.11:6443",
            "--local-addr",
            "127.0.0.1:16443",
        ]

    def test_refuses_to_build_argv_for_a_public_transport(self) -> None:
        # prod has no tunnel; asking for its ts-bridge argv is a programming error.
        t = ClusterTransport("prod", "public", "162.55.57.175", 6443, 16444)
        with pytest.raises(ValueError, match="public"):
            ts_bridge_argv("/opt/ts-bridge", t)


class TestLocateTsBridge:
    def test_env_override_wins_when_it_points_at_a_real_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        binary = tmp_path / "ts-bridge.exe"
        binary.write_text("")
        monkeypatch.setenv("TS_BRIDGE_BIN", str(binary))
        assert locate_ts_bridge() == binary

    def test_missing_binary_raises_actionable_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TS_BRIDGE_BIN", raising=False)
        monkeypatch.setattr(tc, "_TS_BRIDGE_DEFAULTS", ())  # no default locations
        monkeypatch.setattr(tc.shutil, "which", lambda _: None)
        with pytest.raises(FileNotFoundError, match="TS_BRIDGE_BIN"):
            locate_ts_bridge()


class TestTransportState:
    def test_roundtrips_through_disk(self, tmp_path: Path) -> None:
        path = tmp_path / "state.json"
        state = TransportState(env="staging", kind="ts-bridge", pid=4242, local_port=16443, target="100.64.0.11:6443")
        state.save(path)
        assert TransportState.load(path) == state

    def test_load_missing_statefile_returns_none(self, tmp_path: Path) -> None:
        assert TransportState.load(tmp_path / "absent.json") is None

    def test_statefile_path_is_per_env_under_dot_kube(self) -> None:
        p = statefile_path("staging")
        assert p.name == ".kubelab-transport-staging.json"
        assert p.parent.name == ".kube"


class TestCommittedSSOT:
    """The committed common.yaml resolves all three clusters coherently."""

    def test_all_three_resolve_with_distinct_local_ports(self) -> None:
        transports = [resolve_transport(env) for env in ("staging", "prod", "hub")]
        ports = [t.local_port for t in transports]
        assert len(ports) == len(set(ports)), "local_port must be unique per cluster"

    def test_prod_is_public_and_the_others_are_mesh(self) -> None:
        assert resolve_transport("prod").kind == "public"
        assert resolve_transport("staging").kind == "ts-bridge"
        assert resolve_transport("hub").kind == "ts-bridge"

    def test_mesh_targets_are_non_empty_addresses(self) -> None:
        for env in ("staging", "hub"):
            assert resolve_transport(env).target_host, f"{env} mesh target must resolve from the SSOT"
