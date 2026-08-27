"""TOOL-044 (#1380): a rebuilt node's rotated host key must not stop the fetch.

The hub is a Spot VM in a MIG, so a preemption self-heals by **creating a new
machine** — measured at 18 seconds in #1369. The new machine generates a new SSH
host key, and `ssh` refuses a CHANGED key by design. So `fetch-kubeconfig
ENV=hub` died on the recovery path of the thing most likely to need recovering,
and the error named neither the cause nor the remedy.

**The x509 failure is the same defect, downstream.** A recreate rotates the k3s
CA as well, and that CA travels inside `certificate-authority-data` in the very
kubeconfig this fetch reads off the node. So `x509: certificate signed by
unknown authority` against the hub means "your cached kubeconfig is from the
previous machine", and re-fetching is its fix — which the host key was blocking.
One cause, two symptoms. That is why there is no CA-specific code here.

**What is deliberately NOT done**: this is scoped to nodes the SSOT marks
ephemeral, and the tests below pin that scoping as hard as they pin the fix. A
host key is a real protection; purging it globally to unblock the one node that
rotates would trade a fleet-wide check for a single-node convenience.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import toolkit.features.k8s_kubeconfig as kc
from toolkit.features.k8s_kubeconfig import (
    fetch_argv,
    node_identity_is_ephemeral,
    resolve_ssh_hostname,
)


@pytest.fixture
def common(tmp_path: Path) -> Path:
    """Two clusters: one cattle node (no tailscale_ip) and one pet (has one)."""
    path = tmp_path / "common.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "clusters": {
                    "hub": {"node": "gcp1", "ssh_alias": "gcp1", "local_port": 16445},
                    "staging": {"node": "ace1", "ssh_alias": "ace1", "local_port": 16443},
                },
                "networking": {
                    # Recreated on every preemption: MagicDNS only, no literal.
                    "gcp": {"hostname": "gcp1", "tailscale_dns": "gcp1.kubelab.internal"},
                    "nodes": {"ace1": {"hostname": "ace1", "tailscale_ip": "100.64.0.11"}},
                },
            }
        )
    )
    return path


class TestScoping:
    def test_a_node_with_no_tailscale_ip_is_ephemeral(self, common: Path) -> None:
        assert node_identity_is_ephemeral("hub", common) is True

    def test_a_node_that_declares_an_ip_keeps_its_host_key_check(self, common: Path) -> None:
        """The pet half, and the more important assertion of the two.

        Every stable node in the fleet records a `tailscale_ip`. If this ever
        returns True for one of them, the purge silently disables host-key
        verification for a machine whose key rotating IS a real signal.
        """
        assert node_identity_is_ephemeral("staging", common) is False

    def test_an_unknown_cluster_is_not_ephemeral(self, common: Path) -> None:
        """Fail closed: an unrecognised name must not opt into the laxer path."""
        assert node_identity_is_ephemeral("nope", common) is False


class TestFetchArgv:
    def test_the_default_keeps_strict_host_key_checking(self) -> None:
        assert fetch_argv("ace1") == ["ssh", "ace1", "sudo", "cat", "/etc/rancher/k3s/k3s.yaml"]

    def test_accept_new_is_opt_in_and_never_disables_known_hosts(self) -> None:
        """`accept-new` records an UNKNOWN key and still refuses a CHANGED one.

        Which is why it is paired with the purge rather than used alone, and why
        this must not become `UserKnownHostsFile=/dev/null`: that form verifies
        nothing on any run, where this one goes back to verifying the moment the
        machine stops being replaced.
        """
        argv = fetch_argv("gcp1", accept_new=True)
        assert "StrictHostKeyChecking=accept-new" in argv
        assert not any("UserKnownHostsFile" in a for a in argv), "the direct path must keep a real known_hosts"


class TestHostnameResolution:
    def test_the_alias_is_resolved_through_ssh_not_assumed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """known_hosts is keyed by hostname, not by alias.

        Measured: alias `gcp1` resolves to `gcp1.kubelab.internal`. Purging the
        alias would exit 0 and remove nothing — a no-op that reads as a fix.
        """
        captured: list[list[str]] = []

        class _Result:
            returncode = 0
            stdout = "user deployer\nhostname gcp1.kubelab.internal\nport 22\n"

        def fake_run(argv, **kwargs):
            captured.append(argv)
            return _Result()

        monkeypatch.setattr(kc.subprocess, "run", fake_run)
        assert resolve_ssh_hostname("gcp1") == "gcp1.kubelab.internal"
        assert captured == [["ssh", "-G", "gcp1"]]

    def test_it_falls_back_to_the_alias_when_ssh_cannot_be_asked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        class _Result:
            returncode = 255
            stdout = ""

        monkeypatch.setattr(kc.subprocess, "run", lambda argv, **kw: _Result())
        assert resolve_ssh_hostname("gcp1") == "gcp1"


class TestTheErrorSaysSomethingUseful:
    """#1380's title has two halves; the purge only closes the first.

    A node NOT marked ephemeral still fails on a changed key — correctly, that
    is the warning the mechanism exists to produce — but it must not fail mutely.
    """

    def _stub_hostname(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(kc, "resolve_ssh_hostname", lambda alias: f"{alias}.kubelab.internal")

    def test_a_changed_host_key_names_the_cause_and_the_remedy(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._stub_hostname(monkeypatch)
        hint = kc.host_key_hint("vps", "@@@ WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! @@@\n")
        assert hint is not None
        assert "vps.kubelab.internal" in hint
        assert "ssh-keygen -R vps.kubelab.internal" in hint, "the remedy must be runnable as written"
        assert "rebuilt" in hint and "impersonating" in hint, "both readings, so the operator decides"

    def test_it_matches_the_other_wording_ssh_uses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """ssh prints two different lines for this; both exit 255."""
        self._stub_hostname(monkeypatch)
        assert kc.host_key_hint("vps", "Host key verification failed.\n") is not None

    def test_an_unrelated_failure_is_left_alone(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A wrong-hint is worse than none: it sends the operator to delete a
        key when the real problem was their agent."""
        self._stub_hostname(monkeypatch)
        assert kc.host_key_hint("vps", "Permission denied (publickey).\n") is None


class TestPurgeUsesSshKeygen:
    def test_the_entry_is_removed_with_ssh_keygen_not_by_editing_the_file(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With HashKnownHosts on — the default here, measured — hostnames are
        stored hashed, so no text search can locate the entry. Anything that
        greps the file is a no-op on a real workstation."""
        captured: list[list[str]] = []

        class _Result:
            returncode = 0
            stdout = ""
            stderr = ""

        monkeypatch.setattr(kc.subprocess, "run", lambda argv, **kw: (captured.append(argv), _Result())[1])
        assert kc.forget_host_key("gcp1.kubelab.internal") is True
        assert captured == [["ssh-keygen", "-R", "gcp1.kubelab.internal"]]
