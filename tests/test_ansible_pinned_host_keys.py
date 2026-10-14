"""ANSIBLE-066 (#2223): Ansible verifies host keys instead of trusting them on first use.

The inventory used to set `StrictHostKeyChecking=accept-new` for the whole fleet,
so the first run from a fresh workstation trusted whatever key each node
presented. Now every stable node is checked against the pinned file dotfiles
deploys, and only a node whose machine is replaced by design (the hub) keeps the
scoped `accept-new`, until host certificates replace both (#1261).
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from toolkit.features.generator_ansible import AnsibleGenerator

REPO = Path(__file__).resolve().parents[1]
COMMON = REPO / "infra/config/values/common.yaml"
STATIC_INVENTORY = REPO / "infra/ansible/inventories/homelab.yml"


def _networking() -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]


def _hosts(inventory: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for group in inventory["all"]["children"].values():
        out.update(group.get("hosts", {}))
    return out


def _effective_args(inventory: dict[str, Any], host_vars: dict[str, Any]) -> str:
    """What ssh actually receives for a host: a per-host value replaces the global one."""
    return host_vars.get("ansible_ssh_common_args", inventory["all"]["vars"]["ansible_ssh_common_args"])


def _ephemeral_hostnames(net: dict[str, Any]) -> set[str]:
    """Hosts the SSOT marks as replaced by design: tailscale_dns, no tailscale_ip."""
    names = set()
    for block in (net.get("aws", {}), net.get("gcp", {})):
        if block and not block.get("retired") and block.get("tailscale_dns") and not block.get("tailscale_ip"):
            names.add(block["hostname"])
    return names


def _strict(net: dict[str, Any]) -> str:
    return f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={net['ssh_known_hosts']}"


class TestTheSsotDeclaresThePinnedFile:
    def test_the_path_sits_beside_the_key(self) -> None:
        net = _networking()
        assert net["ssh_known_hosts"] == "~/.ssh/known_hosts_pinned", "the file dotfiles deploys (#2356)"


@pytest.mark.parametrize("bootstrap", [False, True])
def test_every_stable_host_is_verified_against_the_pinned_file(bootstrap: bool) -> None:
    """AC1, for the mesh run and the first-provisioning (LAN) run alike."""
    net = _networking()
    inv = AnsibleGenerator()._build_inventory(net, bootstrap=bootstrap)
    assert inv["all"]["vars"]["ansible_ssh_common_args"] == _strict(net)
    stable = {h: hv for h, hv in _hosts(inv).items() if h not in _ephemeral_hostnames(net)}
    assert stable, "the real SSOT has stable nodes"
    for name, hv in stable.items():
        args = _effective_args(inv, hv)
        assert "accept-new" not in args, f"{name} trusts on first use"
        assert _strict(net) in args, f"{name} is not checked against the pinned file"


class TestTheHubException:
    """AC2: derived from the SSOT shape, never a list of names."""

    def test_a_node_replaced_by_design_keeps_accept_new(self) -> None:
        net = _networking()
        ephemeral = _ephemeral_hostnames(net)
        assert ephemeral, "the real SSOT declares the hub by MagicDNS name only"
        hosts = _hosts(AnsibleGenerator()._build_inventory(net))
        for name in ephemeral:
            assert hosts[name].get("ansible_ssh_common_args") == "-o StrictHostKeyChecking=accept-new"

    def test_declaring_an_address_makes_it_stable(self) -> None:
        """A hub that records a tailscale_ip is a pet, and loses the exception."""
        net = copy.deepcopy(_networking())
        hub = net["gcp"]
        hub["tailscale_ip"] = "100.64.0.250"  # any address: only its presence is read
        inv = AnsibleGenerator()._build_inventory(net)
        hv = _hosts(inv)[hub["hostname"]]
        assert "accept-new" not in _effective_args(inv, hv)


class TestBastion:
    """AC3: the jump to the VPS and the proxied hop are both verified."""

    def test_the_jump_and_the_hop_use_the_pinned_file(self) -> None:
        net = _networking()
        inv = AnsibleGenerator()._build_inventory(net, transport="bastion")
        proxied = {
            h: hv
            for h, hv in _hosts(inv).items()
            if "ProxyCommand" in hv.get("ansible_ssh_common_args", "") and h not in _ephemeral_hostnames(net)
        }
        assert proxied, "bastion proxies the mesh-only nodes"
        for name, hv in proxied.items():
            args = hv["ansible_ssh_common_args"]
            assert "accept-new" not in args, f"{name}: a hop trusts on first use"
            assert args.count(f"UserKnownHostsFile={net['ssh_known_hosts']}") == 2, f"{name}: jump and hop"

    def test_the_hub_keeps_its_exception_on_the_proxied_hop_only(self) -> None:
        net = _networking()
        hosts = _hosts(AnsibleGenerator()._build_inventory(net, transport="bastion"))
        for name in _ephemeral_hostnames(net):
            args = hosts[name]["ansible_ssh_common_args"]
            proxy = args.split("ProxyCommand=", 1)[1]
            assert "accept-new" not in proxy, "the VPS is a pet: its jump is verified"
            assert args.split("-o ProxyCommand", 1)[0].strip() == "-o StrictHostKeyChecking=accept-new"


def test_the_committed_inventory_never_trusts_on_first_use() -> None:
    """AC5: the static file the lint target reads carries the same arguments."""
    net = _networking()
    text = STATIC_INVENTORY.read_text(encoding="utf-8")
    assert "accept-new" not in text
    assert yaml.safe_load(text)["all"]["vars"]["ansible_ssh_common_args"] == _strict(net)


class TestRunRefusesWithoutThePinnedFile:
    """AC4: a missing pinned file is named before ansible-playbook runs, not met host by host."""

    @pytest.fixture
    def ansible_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        from types import SimpleNamespace

        from toolkit.cli import infra

        (tmp_path / "playbooks").mkdir()
        (tmp_path / "playbooks" / "site.yml").write_text("---\n")
        (tmp_path / "generated" / "prod").mkdir(parents=True)
        monkeypatch.setattr(infra, "settings", SimpleNamespace(ansible_dir=tmp_path))
        return tmp_path

    def _inventory(self, ansible_dir: Path, known_hosts: Path) -> None:
        args = f"-o StrictHostKeyChecking=yes -o UserKnownHostsFile={known_hosts}"
        inv = {"all": {"vars": {"ansible_ssh_common_args": args}, "children": {}}}
        (ansible_dir / "generated" / "prod" / "hosts.yml").write_text(yaml.safe_dump(inv))

    def _run(self, monkeypatch: pytest.MonkeyPatch) -> list[str]:
        from types import SimpleNamespace

        from toolkit.cli import infra

        ran: list[str] = []
        monkeypatch.setattr(infra.command, "run", lambda cmd, **kw: (ran.append(cmd), SimpleNamespace(returncode=0))[1])
        infra.ansible_run(
            playbook="site",
            env="prod",
            limit=None,
            tags=None,
            check=False,
            become_ask_pass=False,
            extra_vars=None,
            bootstrap=False,
            transport="mesh",
            skip_generate=True,
        )
        return ran

    def test_a_missing_file_stops_the_run_and_is_named(
        self, ansible_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
    ) -> None:
        import typer

        missing = tmp_path / "nowhere" / "known_hosts_pinned"
        self._inventory(ansible_dir, missing)
        with pytest.raises(typer.Exit):
            self._run(monkeypatch)
        out = "".join(capsys.readouterr().out.split())  # the console wraps long lines
        assert "".join(str(missing).split()) in out and "dotfiles" in out

    def test_a_present_file_lets_the_run_through(
        self, ansible_dir: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pinned = tmp_path / "known_hosts_pinned"
        pinned.write_text("")
        self._inventory(ansible_dir, pinned)
        ran = self._run(monkeypatch)
        assert len(ran) == 1 and ran[0].startswith("ansible-playbook")
