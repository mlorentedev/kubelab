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
    rewrite_server_direct,
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


class TestTheMigrationScaffoldingCannotOutliveTheMigration:
    """`clusters.hub-aws` is temporary, and a comment saying so is not a mechanism.

    Raised in review of #1299: the entry carries a REMOVE instruction and nothing
    enforces it. This repository has already recorded what that is worth --
    lesson-365, "a written lesson with no mechanism is a reminder, and a reminder
    fails exactly when the situation arrives".

    The tie is to `networking.aws`, because that is what makes the entry
    meaningful: `hub-aws` exists to address the retiring hub, and the retiring
    hub stops existing in the same commit that removes its networking block. So
    the two are removed together or the suite goes red naming the survivor --
    which is the Phase 5 checklist expressed as a test instead of as a promise.
    """

    def test_hub_aws_and_networking_aws_are_removed_together(self) -> None:
        import yaml

        from toolkit.features.k8s_kubeconfig import _common_path

        config = yaml.safe_load(_common_path().read_text())
        has_entry = "hub-aws" in (config.get("clusters") or {})
        has_networking = "aws" in (config.get("networking") or {})

        assert has_entry == has_networking, (
            "clusters.hub-aws and networking.aws must be removed in the same commit. "
            f"clusters.hub-aws present={has_entry}, networking.aws present={has_networking}. "
            "The scaffolding exists only to address the retiring hub; keeping it after "
            "the hub is gone leaves a cluster entry pointing at nothing, and removing it "
            "while the hub is still live removes the rollback path."
        )

    def test_the_two_hub_entries_never_collide(self) -> None:
        # Both are live simultaneously by design, so they must differ in every
        # field that decides WHICH machine is reached or WHERE the kubeconfig
        # lands. A shared local_port would have the two tunnels fight; a shared
        # node would make the explicit naming decorative.
        clusters = load_clusters()
        if "hub-aws" not in clusters:
            pytest.skip("the migration scaffolding is gone, which is the goal")
        hub, retiring = clusters["hub"], clusters["hub-aws"]
        assert hub.node != retiring.node
        assert hub.ssh_alias != retiring.ssh_alias
        assert hub.local_port != retiring.local_port
        assert output_path("hub") != output_path("hub-aws")


class TestRewriteServerDirect:
    """The mesh-native form: the node's MagicDNS name, no transport in between."""

    def test_writes_the_mesh_name_not_localhost(self) -> None:
        out = rewrite_server_direct(_K3S_YAML, "gcp1.kubelab.internal", 6443)
        assert "server: https://gcp1.kubelab.internal:6443" in out
        assert "https://127.0.0.1:6443" not in out

    def test_preserves_certs_and_line_count(self) -> None:
        out = rewrite_server_direct(_K3S_YAML, "aws1.kubelab.internal", 6443)
        assert "client-key-data: REDACTED" in out
        assert out.count("\n") == _K3S_YAML.count("\n")  # only the server substring changed

    def test_never_disables_tls_verification(self) -> None:
        # The whole reason this form is safe is that k3s puts the MagicDNS name in
        # the serving cert's SANs. If a future edit ever reaches for
        # insecure-skip-tls-verify instead, that is a different feature wearing
        # this one's name.
        out = rewrite_server_direct(_K3S_YAML, "gcp1.kubelab.internal", 6443)
        assert "insecure-skip-tls-verify" not in out
        assert "certificate-authority-data: REDACTED" in out

    def test_distinct_hosts_isolate_hubs(self) -> None:
        # The two-hub window this exists for: aws1 and gcp1 are both live, and a
        # kubeconfig that cannot tell them apart is the defect, not the convenience.
        aws = rewrite_server_direct(_K3S_YAML, "aws1.kubelab.internal", 6443)
        gcp = rewrite_server_direct(_K3S_YAML, "gcp1.kubelab.internal", 6443)
        assert aws != gcp

    def test_raises_when_default_server_absent(self) -> None:
        with pytest.raises(ValueError, match="refusing to write"):
            rewrite_server_direct("server: https://10.0.0.1:6443\n", "gcp1.kubelab.internal", 6443)

    def test_a_recreatable_node_is_addressed_by_name_and_never_by_address(self) -> None:
        """The aws1 lesson, bound to the code instead of asserted in prose.

        This function's docstring originally claimed its host was "a MagicDNS
        name, never a Tailscale IP" and invoked the aws1 lesson to justify it.
        Measured, `--direct` on staging resolves to `100.64.0.11` and on prod to
        a public IP -- so the comment was false about the very function carrying
        it, which is lesson-363's shape reproduced inside the fix for it.

        The rule that IS true binds narrowly: an address that ROTATES must not be
        cached, and the SSOT marks exactly those nodes by declaring
        `tailscale_dns` with no `tailscale_ip`. Asserted here over the real SSOT
        so that adding a recreatable node whose transport resolves to a literal
        fails, instead of being discovered after a preemption.
        """
        import yaml

        # _node_block is reused rather than reimplemented: it resolves a node by
        # HOSTNAME across networking's cloud sections (`gcp1` lives under
        # `networking.gcp`, not `networking.gcp1`), and a second copy of that walk
        # here would be one more thing to keep in step.
        from toolkit.features.k8s_connect import _node_block, resolve_transport
        from toolkit.features.k8s_kubeconfig import _common_path

        config = yaml.safe_load(_common_path().read_text())
        networking = config.get("networking") or {}
        clusters = config.get("clusters") or {}

        # EVERY hub is recreatable, asserted first and separately. Without this the
        # guard below has a hole that a mutation found: adding `tailscale_ip` to a
        # cattle node makes it stop matching `recreatable`, so the loop `continue`s
        # and the node silently stops being checked -- the mutation DISABLES the
        # guard instead of tripping it. The same predicate gates
        # `wait-node-ready.yml`'s known_hosts purge, so the hole is not local to
        # this test: caching an address on a hub would quietly switch off the
        # host-key handling too.
        for name, cluster in clusters.items():
            if not name.startswith("hub"):
                continue
            block = _node_block(networking, str(cluster["node"]))
            assert "tailscale_dns" in block and "tailscale_ip" not in block, (
                f"clusters.{name} is an Argo CD hub, and a hub's machine is replaced "
                f"on every preemption -- so {cluster['node']} must declare "
                "tailscale_dns and NO tailscale_ip. Adding an IP here does not just "
                "cache a rotating address: it removes the node from every check "
                "keyed on that shape, including wait-node-ready's known_hosts purge."
            )

        for name, cluster in clusters.items():
            block = _node_block(networking, str(cluster["node"]))
            recreatable = "tailscale_dns" in block and "tailscale_ip" not in block
            if not recreatable:
                continue
            host = resolve_transport(name).target_host
            assert not host.replace(".", "").isdigit(), (
                f"clusters.{name} names a node whose instance is replaced "
                f"({cluster['node']}), yet --direct would cache the literal {host!r}. "
                "A recreatable node must be addressed by MagicDNS name: the address "
                "rotates on every preemption and the name follows the node."
            )


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
