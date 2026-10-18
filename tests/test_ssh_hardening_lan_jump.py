"""The LAN jump host: rpi4 forwards to the inner-LAN nodes, and no other node does.

The operator's `*-lan` SSH aliases reach the cluster nodes with ProxyJump through
rpi4. They failed with `administratively prohibited` because the `ssh_hardening`
role sets `AllowTcpForwarding no` on every node, rpi4 included (dotfiles#2464).

The decision is declared once, in `common.yaml` (`networking.nodes.rpi4.lan_jump`),
reaches the role as an inventory host var (`ssh_lan_jump_targets`, derived by the
generator), and the template renders a trailing `Match` block only where that list
is non-empty. These tests pin both halves of the property:

- the block is rendered on the jump host and nowhere else;
- every other node renders byte-for-byte what it rendered before the change, held
  as a golden file captured from the template at the commit before this one.

They render the template the way the `template` module does (`trim_blocks` and a kept
trailing newline), for every host of the REAL generated inventory, so a host the
generator hands the variable to by mistake shows up here. The last test asks sshd
itself, with `sshd -T -C user=...`, what it would allow a connection to do: a
rendered block that sshd reads differently is the failure the string checks cannot
see. It skips where there is no sshd.
"""

from __future__ import annotations

import copy
import ipaddress
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import StrictUndefined

from tests.ansible_jinja import ansible_env
from toolkit.features.generator_ansible import AnsibleGenerator

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/ssh_hardening"
COMMON = REPO / "infra/config/values/common.yaml"
GOLDEN = Path(__file__).resolve().parent / "fixtures/ssh_hardening/sshd_config.default.golden"

JUMP_KEY = "rpi4"


def _networking() -> dict[str, Any]:
    return yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]


def _inventory_hosts(networking: dict[str, Any] | None = None) -> dict[str, dict[str, Any]]:
    inventory = AnsibleGenerator()._build_inventory(networking or _networking())
    hosts: dict[str, dict[str, Any]] = {}
    for group in inventory["all"]["children"].values():
        hosts.update(group["hosts"])
    return hosts


def _render(host_vars: dict[str, Any]) -> str:
    """The role's template as Ansible renders it: role defaults, then host vars on top."""
    context = {**yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8")), **host_vars}
    env = ansible_env(str(ROLE / "templates"), undefined=StrictUndefined, trim_blocks=True, keep_trailing_newline=True)
    return env.get_template("sshd_config.j2").render(**context)


def _expected_targets(networking: dict[str, Any]) -> list[str]:
    """Derived here from the data, not copied from the generator: every other node on the inner LAN."""
    lan = ipaddress.ip_network(networking["lan_cidr"])
    return [
        node["lan_ip"]
        for key, node in networking["nodes"].items()
        if key != JUMP_KEY and node.get("lan_ip") and ipaddress.ip_address(node["lan_ip"]) in lan
    ]


def test_the_jump_host_is_declared_in_the_ssot() -> None:
    flagged = [key for key, node in _networking()["nodes"].items() if node.get("lan_jump")]
    assert flagged == [JUMP_KEY]


def test_the_targets_are_the_inner_lan_nodes_and_not_the_wifi_side_or_the_jump_itself() -> None:
    """Guards the guard: an empty or wrong list would make every assertion below vacuous."""
    networking = _networking()
    targets = _expected_targets(networking)
    assert len(targets) >= 4
    assert networking["nodes"][JUMP_KEY]["lan_ip"] not in targets
    # rpi3 lives on the WiFi segment, outside lan_cidr: not behind the jump.
    assert networking["nodes"]["rpi3"]["lan_ip"] not in targets


def test_only_the_jump_host_is_handed_the_forwarding_targets() -> None:
    networking = _networking()
    hosts = _inventory_hosts(networking)
    holders = {name: hv["ssh_lan_jump_targets"] for name, hv in hosts.items() if "ssh_lan_jump_targets" in hv}
    assert list(holders) == [networking["nodes"][JUMP_KEY]["hostname"]]
    assert list(holders.values()) == [_expected_targets(networking)]


def test_every_other_host_renders_exactly_what_it_rendered_before() -> None:
    golden = GOLDEN.read_text(encoding="utf-8")
    jump_host = _networking()["nodes"][JUMP_KEY]["hostname"]
    others = {name: hv for name, hv in _inventory_hosts().items() if name != jump_host}
    assert len(others) >= 5, "the inventory lost its hosts: the comparison below would be vacuous"
    for name, host_vars in others.items():
        assert _render(host_vars) == golden, f"{name} no longer renders the unchanged sshd_config"


def test_the_role_alone_renders_the_unchanged_file() -> None:
    """A caller that passes no inventory var at all (deploy-harden-nodes, a hand-written one)."""
    assert _render({"ansible_user": "manu"}) == GOLDEN.read_text(encoding="utf-8")


def test_the_jump_host_renders_the_golden_file_plus_one_trailing_match_block() -> None:
    networking = _networking()
    jump = _inventory_hosts(networking)[networking["nodes"][JUMP_KEY]["hostname"]]
    rendered = _render(jump)
    golden = GOLDEN.read_text(encoding="utf-8")

    assert rendered.startswith(golden), "the jump host's global section drifted from the other nodes'"
    block = rendered[len(golden) :]
    permit_open = " ".join(f"{ip}:22" for ip in _expected_targets(networking))
    assert block.endswith(
        f"Match User {jump['ansible_user']}\n    AllowTcpForwarding yes\n    PermitOpen {permit_open}\n"
    ), block
    assert [line for line in block.splitlines() if line.startswith("Match ")] == [f"Match User {jump['ansible_user']}"]
    # The Match block is last: anything after its two keywords would be scoped to that user.
    assert block.rstrip().splitlines()[-2:] == [
        "    AllowTcpForwarding yes",
        f"    PermitOpen {permit_open}",
    ]
    assert "AllowAgentForwarding yes" not in rendered
    assert rendered.count("AllowAgentForwarding no") == 1


def test_the_forwarding_user_follows_the_inventory_user() -> None:
    targets = _expected_targets(_networking())
    assert "Match User deployer\n" in _render({"ansible_user": "deployer", "ssh_lan_jump_targets": targets})


def test_the_generator_refuses_a_second_jump_host() -> None:
    networking = copy.deepcopy(_networking())
    networking["nodes"]["ace1"]["lan_jump"] = True
    with pytest.raises(ValueError, match="more than one lan_jump host"):
        AnsibleGenerator()._build_inventory(networking)


def test_the_generator_refuses_a_jump_with_nothing_behind_it() -> None:
    networking = copy.deepcopy(_networking())
    networking["nodes"] = {JUMP_KEY: networking["nodes"][JUMP_KEY]}
    with pytest.raises(ValueError, match="nothing to jump to"):
        AnsibleGenerator()._build_inventory(networking)


def test_without_a_declaration_no_host_gets_the_variable() -> None:
    networking = copy.deepcopy(_networking())
    del networking["nodes"][JUMP_KEY]["lan_jump"]
    assert not [name for name, hv in _inventory_hosts(networking).items() if "ssh_lan_jump_targets" in hv]


@pytest.mark.allow_host_clients(reason="runs the local sshd in test mode (-T); it opens no socket and starts no daemon")
def test_sshd_itself_allows_the_forward_to_the_declared_nodes_only(tmp_path: Path) -> None:
    sshd = shutil.which("sshd") or ("/usr/sbin/sshd" if Path("/usr/sbin/sshd").exists() else None)
    keygen = shutil.which("ssh-keygen")
    if sshd is None or keygen is None:
        pytest.skip("no sshd/ssh-keygen: what sshd allows the jump user was NOT checked")

    networking = _networking()
    jump = _inventory_hosts(networking)[networking["nodes"][JUMP_KEY]["hostname"]]
    config = tmp_path / "sshd_config"
    config.write_text(_render(jump), encoding="utf-8")
    host_key = tmp_path / "host_key"
    subprocess.run([keygen, "-q", "-t", "ed25519", "-N", "", "-f", str(host_key)], check=True)

    def effective(user: str) -> dict[str, str]:
        out = subprocess.run(
            [sshd, "-T", "-h", str(host_key), "-f", str(config), "-C", f"user={user},host=h,addr=203.0.113.9"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        return dict(line.split(" ", 1) for line in out.splitlines() if " " in line)

    jump_user = effective(jump["ansible_user"])
    assert jump_user["allowtcpforwarding"] == "yes"
    assert jump_user["permitopen"] == " ".join(f"{ip}:22" for ip in _expected_targets(networking))
    assert jump_user["allowagentforwarding"] == "no"

    anyone_else = effective("somebody-else")
    assert anyone_else["allowtcpforwarding"] == "no"
    assert anyone_else["permitopen"] == "any"
