"""`make edge-lan-link` joins the operator's laptop to the lab LAN (NET-005 AC11, task 33).

It replaces a NetworkManager profile made by hand on 2026-10-25. The edge serves
DHCP on that LAN, so the profile asks for a lease and renders only what the lease
cannot say:

- management (the default): no default route and no DNS from the edge, no IPv6.
  The laptop keeps its own internet and reaches the LAN beside it;
- `ROUTE=1`: the edge becomes the default route, for the portal login with the
  laptop's own Wi-Fi off;
- `REMOVE=1`: the profile goes, and nothing else does.

Either way, `networking.lan_cidr` is routed out the wire by a rule that comes
before tailscale's `lookup 52`. The edge advertises that CIDR to the tailnet, and
a laptop that accepts routes would otherwise send its LAN traffic through the
tailnet, which rides on the uplink: the LAN path would die with the thing it is
there to diagnose.

nmcli is mocked: every test reads the commands the module would run.
"""

from __future__ import annotations

import ipaddress
import re
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]
LAN_CIDR = NETWORKING["lan_cidr"]
TAILSCALE_TABLE_RULE = 5270  # `from all lookup 52`, measured on the operator's laptop
ADAPTER = "enx020000000001"
DEVICES = f"{ADAPTER}:ethernet:connected\nveth01916b3:ethernet:unmanaged\nwlp1s0:wifi:connected\n"


class Nmcli:
    """Answers nmcli's reads and records its writes."""

    def __init__(self, profiles: str = "", devices: str = DEVICES) -> None:
        self.profiles = profiles
        self.devices = devices
        self.writes: list[list[str]] = []

    def __call__(self, argv: list[str], **_: Any) -> subprocess.CompletedProcess[str]:
        assert argv[0] == "nmcli"
        if argv[1:3] == ["-t", "-f"] and "device" in argv:
            return subprocess.CompletedProcess(argv, 0, self.devices, "")
        if argv[1:3] == ["-t", "-f"] and "connection" in argv:
            return subprocess.CompletedProcess(argv, 0, self.profiles, "")
        self.writes.append(argv)
        return subprocess.CompletedProcess(argv, 0, "", "")


def _settings(command: list[str]) -> dict[str, str]:
    """The `setting value` pairs after the profile name."""
    start = next(i for i, word in enumerate(command) if word == "ipv4.method")
    pairs = command[start:]
    return dict(zip(pairs[::2], pairs[1::2], strict=True))


def _link(nmcli: Nmcli, **kwargs: Any) -> int:
    from toolkit.features.edge_lan_link import apply

    with mock.patch("toolkit.features.edge_lan_link.shutil.which", return_value="/usr/bin/nmcli"):
        return apply(LAN_CIDR, run=nmcli, **kwargs)


# ------------------------------------------------------------------- the profile


def test_management_mode_takes_neither_the_route_nor_the_dns() -> None:
    nmcli = Nmcli()
    assert _link(nmcli) == 0
    settings = _settings(nmcli.writes[0])
    assert settings["ipv4.method"] == "auto", "the address is the edge's lease"
    assert settings["ipv4.never-default"] == "yes"
    assert settings["ipv4.ignore-auto-dns"] == "yes"
    assert settings["ipv6.method"] == "disabled"


def test_route_mode_makes_the_edge_the_default_route() -> None:
    nmcli = Nmcli()
    assert _link(nmcli, route=True) == 0
    settings = _settings(nmcli.writes[0])
    assert settings["ipv4.never-default"] == "no"
    assert settings["ipv4.ignore-auto-dns"] == "no", "the portal's names resolve through the edge"
    assert settings["ipv6.method"] == "disabled"


@pytest.mark.parametrize("route", [False, True])
def test_the_lan_goes_out_the_wire_before_the_tailnet_can_take_it(route: bool) -> None:
    nmcli = Nmcli()
    _link(nmcli, route=route)
    rule = _settings(nmcli.writes[0])["ipv4.routing-rules"]
    match = re.fullmatch(r"priority (\d+) to (\S+) table 254", rule)
    assert match, rule
    assert int(match.group(1)) < TAILSCALE_TABLE_RULE
    assert match.group(2) == LAN_CIDR


def test_the_cidr_is_the_ssot_one() -> None:
    from toolkit.features.edge_lan_link import profile_settings

    other = "198.51.100.0/24"
    pairs = profile_settings(other, route=False)
    assert f"to {other} table" in dict(zip(pairs[::2], pairs[1::2], strict=True))["ipv4.routing-rules"]
    with pytest.raises(ValueError):
        profile_settings("not-a-cidr", route=False)
    assert ipaddress.ip_network(LAN_CIDR)


def test_the_profile_is_brought_up_and_never_autoconnects() -> None:
    """It holds the adapter only when asked: plugged into another network, the adapter
    must not take this profile's rule or, in route mode, its default route."""
    from toolkit.features.edge_lan_link import PROFILE

    nmcli = Nmcli()
    _link(nmcli)
    add, up = nmcli.writes
    assert add[:9] == ["nmcli", "connection", "add", "type", "ethernet", "con-name", PROFILE, "ifname", ADAPTER]
    assert _settings(add)["connection.autoconnect"] == "no"
    assert up == ["nmcli", "connection", "up", PROFILE]


def test_a_second_run_modifies_the_profile_instead_of_adding_another() -> None:
    from toolkit.features.edge_lan_link import PROFILE

    nmcli = Nmcli(profiles=f"Wired connection 1\n{PROFILE}\n")
    assert _link(nmcli, route=True) == 0
    modify, up = nmcli.writes
    assert modify[:6] == ["nmcli", "connection", "modify", PROFILE, "connection.interface-name", ADAPTER]
    assert _settings(modify)["ipv4.never-default"] == "no"
    assert up == ["nmcli", "connection", "up", PROFILE]


# ------------------------------------------------------------------- the adapter


def test_the_adapter_is_the_one_managed_ethernet_device() -> None:
    """Docker's veth pairs are ethernet too; NetworkManager leaves them unmanaged."""
    nmcli = Nmcli()
    _link(nmcli)
    assert nmcli.writes[0][8] == ADAPTER


def test_a_named_adapter_wins() -> None:
    nmcli = Nmcli(devices=f"{DEVICES}enx020000000002:ethernet:disconnected\n")
    _link(nmcli, interface="enx020000000002")
    assert nmcli.writes[0][8] == "enx020000000002"


@pytest.mark.parametrize(
    "devices",
    ["veth01916b3:ethernet:unmanaged\n", f"{DEVICES}enx020000000002:ethernet:disconnected\n"],
    ids=["none", "two"],
)
def test_no_single_adapter_is_refused_with_the_candidates(devices: str) -> None:
    from toolkit.features.edge_lan_link import LanLinkRefused

    nmcli = Nmcli(devices=devices)
    with pytest.raises(LanLinkRefused, match=r"ERROR: .* WHY: .* FIX: .*IFACE="):
        _link(nmcli)
    assert nmcli.writes == []


def test_without_networkmanager_it_refuses() -> None:
    from toolkit.features.edge_lan_link import LanLinkRefused, apply

    nmcli = Nmcli()
    with (
        mock.patch("toolkit.features.edge_lan_link.shutil.which", return_value=None),
        pytest.raises(LanLinkRefused, match=r"ERROR: .*nmcli.* FIX: "),
    ):
        apply(LAN_CIDR, run=nmcli)
    assert nmcli.writes == []


# ------------------------------------------------------------------- removal


def test_remove_deletes_this_profile_and_nothing_else() -> None:
    from toolkit.features.edge_lan_link import PROFILE

    nmcli = Nmcli(profiles=f"lab-bootstrap\nWired connection 1\n{PROFILE}\n")
    assert _link(nmcli, remove=True) == 0
    assert nmcli.writes == [["nmcli", "connection", "delete", PROFILE]]


def test_remove_with_no_profile_is_a_no_op() -> None:
    nmcli = Nmcli(profiles="Wired connection 1\n")
    assert _link(nmcli, remove=True) == 0
    assert nmcli.writes == []


def test_a_failed_nmcli_write_fails_the_target() -> None:
    nmcli = Nmcli()

    def failing(argv: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        result = nmcli(argv, **kwargs)
        return result if argv[1] == "-t" else subprocess.CompletedProcess(argv, 4, "", "boom")

    assert _link(failing) == 4  # type: ignore[arg-type]


# ------------------------------------------------------------- the operator's side


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        ([], {"route": False, "remove": False, "interface": None}),
        (["--route"], {"route": True, "remove": False, "interface": None}),
        (["--remove"], {"route": False, "remove": True, "interface": None}),
        (["--interface", ADAPTER], {"route": False, "remove": False, "interface": ADAPTER}),
    ],
)
def test_the_command_passes_the_ssot_cidr_and_the_mode(args: list[str], expected: dict[str, Any]) -> None:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    with mock.patch("toolkit.features.edge_lan_link.apply", return_value=0) as apply:
        result = CliRunner().invoke(app, ["edge", "lan-link", *args])
    assert result.exit_code == 0, result.output
    assert apply.call_args.args == (LAN_CIDR,)
    assert apply.call_args.kwargs == expected


def test_route_and_remove_together_are_refused() -> None:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    with mock.patch("toolkit.features.edge_lan_link.apply") as apply:
        result = CliRunner().invoke(app, ["edge", "lan-link", "--route", "--remove"])
    assert result.exit_code == 1
    assert not apply.called


def test_the_makefile_target_calls_the_command() -> None:
    makefile = (REPO / "Makefile").read_text()
    target = re.search(r"^edge-lan-link:.*\n((?:\t.*\n)+)", makefile, re.M)
    assert target, "no edge-lan-link target"
    recipe = target.group(1)
    assert "infra edge lan-link" in recipe
    for make_var, flag in [("ROUTE", "--route"), ("REMOVE", "--remove"), ("IFACE", "--interface $(IFACE)")]:
        assert f"$(if $({make_var}),{flag}" in recipe, make_var
