"""The control-plane bootstrap forward: one account on the VPS may forward to Headscale, and nowhere else.

Clients on a network that sinkholes or inspects `vpn.kubelab.live` reach Headscale with
`ts-bridge connect --bootstrap-ssh`, an `ssh -N -D` SOCKS forward through the VPS
(VPN-ACL-015, #2862). The `ssh_hardening` role forbids TCP forwarding on every node, so
the path is declared: a host var `ssh_bootstrap_forward` makes the template render a
trailing `Match User` block for that account whose only `PermitOpen` is the control
plane. `transitional_users` keeps the clients that still use another account working,
narrowed to the same destination, until they move.

These tests render the template the way `test_ssh_hardening_lan_jump.py` does and hold
every host without the variable to the same golden file. The last test asks sshd itself
what each user may do, and skips where there is no sshd.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from tests.test_ssh_hardening_lan_jump import GOLDEN, _render

CONTROL_PLANE = "vpn.kubelab.live:443"
FORWARD = {"user": "hs-bootstrap", "permit_open": CONTROL_PLANE, "transitional_users": []}

BOOTSTRAP_BLOCK = (
    "Match User hs-bootstrap\n"
    "    AllowTcpForwarding local\n"
    f"    PermitOpen {CONTROL_PLANE}\n"
    "    AllowStreamLocalForwarding no\n"
    "    AllowAgentForwarding no\n"
    "    X11Forwarding no\n"
    "    PermitTunnel no\n"
    "    PermitTTY no\n"
    "    ForceCommand /usr/sbin/nologin\n"
)


def _vps(**forward: Any) -> dict[str, Any]:
    return {"ansible_user": "deployer", "ssh_bootstrap_forward": {**FORWARD, **forward}}


def _match_blocks(rendered: str) -> dict[str, list[str]]:
    """Every Match block's keyword lines, keyed by its Match line. Comments and blanks dropped."""
    blocks: dict[str, list[str]] = {}
    current: list[str] | None = None
    for line in rendered.splitlines():
        if line.startswith("Match "):
            current = blocks.setdefault(line, [])
        elif current is not None and line.strip() and not line.lstrip().startswith("#"):
            current.append(line.strip())
    return blocks


def test_the_vps_renders_the_golden_file_plus_one_bootstrap_block() -> None:
    rendered = _render(_vps())
    golden = GOLDEN.read_text(encoding="utf-8")

    assert rendered.startswith(golden), "the VPS's global section drifted from the other nodes'"
    assert rendered.endswith(BOOTSTRAP_BLOCK), rendered[len(golden) :]
    assert list(_match_blocks(rendered)) == ["Match User hs-bootstrap"]
    # The global default is untouched: every other account still forwards nothing.
    assert rendered.count("\nAllowTcpForwarding no\n") == 1


def test_a_transitional_user_is_narrowed_to_the_control_plane() -> None:
    blocks = _match_blocks(_render(_vps(transitional_users=["deployer"])))
    assert list(blocks) == ["Match User hs-bootstrap", "Match User deployer"]
    assert blocks["Match User deployer"] == [
        "AllowTcpForwarding local",
        f"PermitOpen {CONTROL_PLANE}",
        "AllowStreamLocalForwarding no",
    ]


def test_without_transitional_users_no_other_account_gets_a_block() -> None:
    assert list(_match_blocks(_render(_vps(transitional_users=[])))) == ["Match User hs-bootstrap"]


def test_both_blocks_render_each_closed_and_the_global_default_stays_no() -> None:
    """A host that is both the LAN jump and the bootstrap endpoint (none is today)."""
    host = {**_vps(transitional_users=["deployer"]), "ansible_user": "manu", "ssh_lan_jump_targets": ["172.16.1.2"]}
    rendered = _render(host)
    blocks = _match_blocks(rendered)

    assert list(blocks) == ["Match User manu", "Match User hs-bootstrap", "Match User deployer"]
    assert blocks["Match User manu"] == ["AllowTcpForwarding yes", "PermitOpen 172.16.1.2:22"]
    assert blocks["Match User hs-bootstrap"] == [line.strip() for line in BOOTSTRAP_BLOCK.splitlines()[1:]]
    assert rendered.count("\nAllowTcpForwarding no\n") == 1


def test_the_role_alone_still_renders_the_golden_file() -> None:
    assert _render({"ansible_user": "deployer", "ssh_bootstrap_forward": {}}) == GOLDEN.read_text(encoding="utf-8")


@pytest.mark.allow_host_clients(reason="runs the local sshd in test mode (-T); it opens no socket and starts no daemon")
def test_sshd_itself_limits_each_user_to_what_was_declared(tmp_path: Path) -> None:
    sshd = shutil.which("sshd") or ("/usr/sbin/sshd" if Path("/usr/sbin/sshd").exists() else None)
    keygen = shutil.which("ssh-keygen")
    if sshd is None or keygen is None:
        pytest.skip("no sshd/ssh-keygen: what sshd allows the bootstrap user was NOT checked")

    config = tmp_path / "sshd_config"
    config.write_text(_render(_vps(transitional_users=["deployer"])), encoding="utf-8")
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

    bootstrap = effective("hs-bootstrap")
    assert bootstrap["allowtcpforwarding"] == "local"
    assert bootstrap["permitopen"] == CONTROL_PLANE
    assert bootstrap["permittty"] == "no"
    assert bootstrap["allowagentforwarding"] == "no"
    assert bootstrap["allowstreamlocalforwarding"] == "no"
    assert bootstrap["permittunnel"] == "no"
    assert bootstrap["forcecommand"] == "/usr/sbin/nologin"

    deployer = effective("deployer")
    assert deployer["allowtcpforwarding"] == "local"
    assert deployer["permitopen"] == CONTROL_PLANE
    assert deployer["permittty"] == "yes", "the transitional block must not take the operator's shell away"

    anyone_else = effective("somebody-else")
    assert anyone_else["allowtcpforwarding"] == "no"
