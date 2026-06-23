"""Tests for the fetch-kubeconfig feature (ADR-052 / #723).

Cover the pure helpers — SSOT load, server rewrite, ssh argv, output path —
without any network. The actual SSH read is the only side effect and lives in
`fetch_kubeconfig`, which is not exercised here.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from toolkit.features import k8s_kubeconfig as kc
from toolkit.features.k8s_kubeconfig import (
    ClusterAccess,
    _is_connect_failure,
    fetch_argv,
    load_cluster_access,
    load_clusters,
    output_path,
    rewrite_server,
)

# A minimal but realistic k3s admin kubeconfig (apiserver on the 127.0.0.1 default).
_K3S_YAML = """\
apiVersion: v1
clusters:
- cluster:
    certificate-authority-data: REDACTED
    server: https://127.0.0.1:6443
  name: default
contexts:
- context:
    cluster: default
    user: default
  name: default
current-context: default
kind: Config
users:
- name: default
  user:
    client-certificate-data: REDACTED
    client-key-data: REDACTED
"""


class TestRewriteServer:
    """ADR-052 D1: only the port changes; the host stays 127.0.0.1."""

    def test_rewrites_only_the_port_keeping_localhost(self) -> None:
        out = rewrite_server(_K3S_YAML, 16443)
        assert "server: https://127.0.0.1:16443" in out
        assert "https://127.0.0.1:6443" not in out

    def test_distinct_ports_isolate_clusters(self) -> None:
        # Distinct local ports are what let several tunnels coexist.
        assert rewrite_server(_K3S_YAML, 16444) != rewrite_server(_K3S_YAML, 16445)

    def test_preserves_certs_and_line_count(self) -> None:
        out = rewrite_server(_K3S_YAML, 16443)
        assert "client-key-data: REDACTED" in out
        assert out.count("\n") == _K3S_YAML.count("\n")  # only the server substring changed

    def test_raises_when_default_server_absent(self) -> None:
        with pytest.raises(ValueError, match="refusing to write"):
            rewrite_server("server: https://10.0.0.1:6443\n", 16443)


class TestClusterSSOT:
    """`clusters.<name>` is read from common.yaml and validated."""

    @pytest.fixture
    def common_yaml(self, tmp_path: Path) -> Path:
        p = tmp_path / "common.yaml"
        p.write_text(
            "clusters:\n"
            "  staging:\n"
            "    node: ace1\n"
            "    ssh_alias: ace1\n"
            "    local_port: 16443\n"
            "  hub:\n"
            "    node: aws1\n"
            "    ssh_alias: aws1\n"
            "    local_port: 16445\n"
        )
        return p

    def test_load_clusters_parses_entries(self, common_yaml: Path) -> None:
        clusters = load_clusters(common_yaml)
        assert clusters["staging"] == ClusterAccess("staging", "ace1", "ace1", 16443)
        assert clusters["hub"].local_port == 16445

    def test_unknown_cluster_lists_valid_names(self, common_yaml: Path) -> None:
        with pytest.raises(KeyError, match="hub, staging"):
            load_cluster_access("dev", common_yaml)

    def test_missing_required_key_raises(self, tmp_path: Path) -> None:
        p = tmp_path / "common.yaml"
        p.write_text("clusters:\n  staging:\n    node: ace1\n")  # no ssh_alias / local_port
        with pytest.raises(KeyError, match="ssh_alias"):
            load_clusters(p)


class TestArgvAndPath:
    def test_fetch_argv_is_a_remote_cat(self) -> None:
        assert fetch_argv("ace1") == ["ssh", "ace1", "sudo", "cat", "/etc/rancher/k3s/k3s.yaml"]

    def test_output_path_follows_kubeconfig_pattern(self) -> None:
        assert output_path("staging").name == "kubelab-staging-config"
        assert output_path("staging").parent.name == ".kube"


class TestIsConnectFailure:
    """Pure predicate: network failures fall back; auth failures raise loud."""

    def test_timeout_is_a_connect_failure(self) -> None:
        assert _is_connect_failure(255, "ssh: connect to host ace1 port 22: Connection timed out")

    def test_no_route_is_a_connect_failure(self) -> None:
        assert _is_connect_failure(255, "No route to host")

    def test_connection_refused_is_a_connect_failure(self) -> None:
        assert _is_connect_failure(255, "Connection refused")

    def test_permission_denied_is_not_a_connect_failure(self) -> None:
        assert not _is_connect_failure(255, "Permission denied (publickey,gssapi-keyex)")

    def test_non_255_exit_code_is_not_a_connect_failure(self) -> None:
        assert not _is_connect_failure(1, "No route to host")

    def test_success_is_not_a_connect_failure(self) -> None:
        assert not _is_connect_failure(0, "")


class TestFetchKubeconfig:
    """Orchestrator: try direct SSH, fall back on connect failure, raise on auth failure."""

    def _setup(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        common = tmp_path / "common.yaml"
        common.write_text(
            "clusters:\n  staging:\n    node: ace1\n    ssh_alias: ace1\n    local_port: 16443\n"
        )
        dest = tmp_path / ".kube" / "kubelab-staging-config"
        monkeypatch.setattr(kc, "_common_path", lambda: common)
        monkeypatch.setattr(kc, "output_path", lambda env: dest)
        return common, dest

    def test_direct_ssh_success_writes_rewritten_kubeconfig(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        _common, dest = self._setup(tmp_path, monkeypatch)
        mocker.patch(
            "toolkit.features.k8s_kubeconfig.subprocess.run",
            return_value=subprocess.CompletedProcess([], 0, _K3S_YAML, ""),
        )

        out = kc.fetch_kubeconfig("staging")

        assert out == dest
        assert "server: https://127.0.0.1:16443" in dest.read_text()
        assert "https://127.0.0.1:6443" not in dest.read_text()

    def test_falls_back_to_tunnel_on_connect_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        _common, dest = self._setup(tmp_path, monkeypatch)
        mocker.patch(
            "toolkit.features.k8s_kubeconfig.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 255, "", "ssh: connect to host ace1 port 22: Connection timed out"
            ),
        )
        tunnel_mock = mocker.patch.object(kc, "_fetch_via_tunnel", return_value=_K3S_YAML)

        kc.fetch_kubeconfig("staging")

        tunnel_mock.assert_called_once()
        assert "server: https://127.0.0.1:16443" in dest.read_text()

    def test_raises_loud_on_auth_failure_no_tunnel_fallback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mocker
    ) -> None:
        _common, dest = self._setup(tmp_path, monkeypatch)
        mocker.patch(
            "toolkit.features.k8s_kubeconfig.subprocess.run",
            return_value=subprocess.CompletedProcess(
                [], 255, "", "Permission denied (publickey,gssapi-keyex)"
            ),
        )
        tunnel_mock = mocker.patch.object(kc, "_fetch_via_tunnel")

        with pytest.raises(RuntimeError, match="SSH fetch failed"):
            kc.fetch_kubeconfig("staging")

        tunnel_mock.assert_not_called()


class TestCommittedSSOT:
    """The committed common.yaml declares the three clusters coherently."""

    def test_declares_staging_prod_hub_with_distinct_ports(self) -> None:
        clusters = load_clusters()  # real common.yaml via settings.project_root
        assert {"staging", "prod", "hub"} <= set(clusters)
        ports = [c.local_port for c in clusters.values()]
        assert len(ports) == len(set(ports)), "local_port must be unique per cluster"
