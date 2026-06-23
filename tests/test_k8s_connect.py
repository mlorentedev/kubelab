"""Tests for the cluster-access transport feature (ADR-052 Phase 2 / TOOL-014).

Cover the pure helpers — transport resolution from the SSOT, ts-bridge argv,
binary discovery, and transport-state (de)serialization — without any network.
The process spawn / port probe / kill live in connect/disconnect/status, which
are not exercised here (they need a live mesh).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from toolkit.features import k8s_connect as tc
from toolkit.features.k8s_connect import (
    ClusterTransport,
    TransportState,
    find_free_port,
    locate_ts_bridge,
    resolve_ssh_tunnel_params,
    resolve_ssh_user,
    resolve_transport,
    statefile_path,
    ts_bridge_argv,
    ts_bridge_tunnel,
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
  ssh_users:
    homelab: manu
    cloud: deployer
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
    def test_builds_a_manual_mode_target_and_local_bind_for_apiserver(self) -> None:
        argv = ts_bridge_argv("/opt/ts-bridge", "100.64.0.11", 6443, 16443)
        assert argv == [
            "/opt/ts-bridge",
            "connect",
            "--manual-mode",
            "--target",
            "100.64.0.11:6443",
            "--local-addr",
            "127.0.0.1:16443",
        ]

    def test_builds_argv_for_ssh_target_port_22(self) -> None:
        argv = ts_bridge_argv("/opt/ts-bridge", "100.64.0.11", 22, 19022)
        assert "--target" in argv
        assert "100.64.0.11:22" in argv
        assert "127.0.0.1:19022" in argv


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


class TestResolveSshUser:
    """Pure helper: ssh_users from networking SSOT-014a (no config load)."""

    def test_homelab_node_gets_homelab_user(self) -> None:
        networking = {"nodes": {"ace1": {}}, "ssh_users": {"homelab": "manu", "cloud": "deployer"}}
        assert resolve_ssh_user(networking, "ace1") == "manu"

    def test_cloud_node_gets_cloud_user(self) -> None:
        networking = {"nodes": {}, "ssh_users": {"homelab": "manu", "cloud": "deployer"}}
        assert resolve_ssh_user(networking, "vps") == "deployer"

    def test_missing_category_raises_keyerror(self) -> None:
        networking = {"nodes": {"ace1": {}}, "ssh_users": {}}  # homelab not declared
        with pytest.raises(KeyError, match="homelab"):
            resolve_ssh_user(networking, "ace1")


class TestResolveSshTunnelParams:
    def test_staging_returns_homelab_user_and_mesh_host(self, common_yaml: Path) -> None:
        user, host = resolve_ssh_tunnel_params("staging", common_yaml)
        assert user == "manu"
        assert host == "100.64.0.11"

    def test_hub_returns_cloud_user_and_mesh_host(self, common_yaml: Path) -> None:
        user, host = resolve_ssh_tunnel_params("hub", common_yaml)
        assert user == "deployer"
        assert host == "100.64.0.7"

    def test_prod_has_no_mesh_address_raises(self, tmp_path: Path) -> None:
        # prod only has a public_ip, no tailscale address — tunnel not applicable.
        p = tmp_path / "common.yaml"
        p.write_text(
            "clusters:\n  prod:\n    node: vps\n    ssh_alias: vps\n    local_port: 16444\n"
            "networking:\n  vps:\n    public_ip: 1.2.3.4\n  ssh_users:\n    cloud: deployer\n"
        )
        with pytest.raises(KeyError, match="mesh address"):
            resolve_ssh_tunnel_params("prod", p)

    def test_unknown_cluster_raises(self, common_yaml: Path) -> None:
        with pytest.raises(KeyError, match="hub, prod, staging"):
            resolve_ssh_tunnel_params("dev", common_yaml)


class TestTsBridgeTunnel:
    """Context manager guarantees teardown and yields pid."""

    def _mock_proc(self) -> MagicMock:
        proc = MagicMock()
        proc.pid = 42
        proc.returncode = None
        proc.poll.return_value = None
        return proc

    def test_yields_pid_and_terminates_on_normal_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_binary = tmp_path / "ts-bridge"
        fake_binary.write_text("")
        monkeypatch.setattr(tc, "locate_ts_bridge", lambda: fake_binary)
        mock_proc = self._mock_proc()
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: mock_proc)
        monkeypatch.setattr(tc, "_port_listening", lambda *a, **kw: True)
        terminated: list[int] = []
        monkeypatch.setattr(tc, "_terminate", lambda pid: terminated.append(pid))

        with ts_bridge_tunnel("100.64.0.11", 22, 19022) as pid:
            assert pid == 42

        assert terminated == [42]

    def test_guaranteed_teardown_when_body_raises(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_binary = tmp_path / "ts-bridge"
        fake_binary.write_text("")
        monkeypatch.setattr(tc, "locate_ts_bridge", lambda: fake_binary)
        mock_proc = self._mock_proc()
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: mock_proc)
        monkeypatch.setattr(tc, "_port_listening", lambda *a, **kw: True)
        terminated: list[int] = []
        monkeypatch.setattr(tc, "_terminate", lambda pid: terminated.append(pid))

        with pytest.raises(ValueError, match="injected"):
            with ts_bridge_tunnel("100.64.0.11", 22, 19022):
                raise ValueError("injected failure")

        assert terminated == [42], "bridge process must be terminated even when body raises"

    def test_early_exit_raises_before_yielding(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        fake_binary = tmp_path / "ts-bridge"
        fake_binary.write_text("")
        monkeypatch.setattr(tc, "locate_ts_bridge", lambda: fake_binary)
        mock_proc = self._mock_proc()
        mock_proc.poll.return_value = 1  # process exited immediately
        monkeypatch.setattr(subprocess, "Popen", lambda *a, **kw: mock_proc)
        monkeypatch.setattr(tc, "_port_listening", lambda *a, **kw: False)
        terminated: list[int] = []
        monkeypatch.setattr(tc, "_terminate", lambda pid: terminated.append(pid))

        with pytest.raises(RuntimeError, match="exited early"):
            with ts_bridge_tunnel("100.64.0.11", 22, 19022):
                pass  # should not be reached

        assert terminated == [42]


class TestFindFreePort:
    def test_returns_a_valid_loopback_port(self) -> None:
        port = find_free_port()
        assert 1024 <= port <= 65535


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

    def test_ssh_tunnel_params_resolve_for_staging(self) -> None:
        user, host = resolve_ssh_tunnel_params("staging")
        assert user and host, "staging must have ssh_user + mesh_host in common.yaml"
