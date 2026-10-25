"""Join the operator's laptop to the lab LAN, the edge's management path (NET-005 AC11).

The edge serves DHCP on the lab LAN, so the profile asks for a lease and renders
only what a lease cannot say: whether the edge may be the default route and the
DNS (only for the portal login, with the laptop's own Wi-Fi off), and a rule that
sends `networking.lan_cidr` out the wire.

The rule is the reason this is not a plain DHCP profile. The edge advertises the
lab LAN to the tailnet, and on a laptop that accepts routes tailscale's
`lookup 52` comes before the main table, so the LAN traffic would leave through
the tailnet. The tailnet rides on the uplink, so the LAN path would go down with
the very thing it exists to diagnose.

NetworkManager only: the profile replaces one made by hand with nmcli. A Mac
needs its own implementation.
"""

from __future__ import annotations

import ipaddress
import shutil
import subprocess
from collections.abc import Callable

PROFILE = "kubelab-edge-lan"
# Below tailscale's `from all lookup 52` (5270). 254 is the main table, where the
# adapter's connected route is.
RULE_PRIORITY = 5200

Runner = Callable[..., subprocess.CompletedProcess[str]]


class LanLinkRefused(RuntimeError):
    """The laptop cannot take the profile as asked."""


def profile_settings(lan_cidr: str, route: bool) -> list[str]:
    """The profile's settings, as nmcli `setting value` pairs."""
    cidr = ipaddress.ip_network(lan_cidr)
    return [
        "ipv4.method",
        "auto",
        "ipv4.never-default",
        "no" if route else "yes",
        "ipv4.ignore-auto-dns",
        "no" if route else "yes",
        "ipv4.routing-rules",
        f"priority {RULE_PRIORITY} to {cidr} table 254",
        "ipv6.method",
        "disabled",
        "connection.autoconnect",
        "no",
    ]


def _read(run: Runner, *fields_and_object: str) -> list[str]:
    result = run(["nmcli", "-t", "-f", *fields_and_object], capture_output=True, text=True, check=False)
    return [line for line in result.stdout.splitlines() if line]


def _adapter(run: Runner, interface: str | None) -> str:
    if interface:
        return interface
    # Docker's veth pairs are ethernet too; NetworkManager leaves them unmanaged.
    adapters = [
        line.split(":")[0]
        for line in _read(run, "DEVICE,TYPE,STATE", "device")
        if line.split(":")[1:2] == ["ethernet"] and not line.endswith(":unmanaged")
    ]
    if len(adapters) != 1:
        raise LanLinkRefused(
            f"ERROR: expected one Ethernet adapter, found {', '.join(adapters) or 'none'}. "
            "WHY: the profile is bound to the adapter on the lab switch. "
            "FIX: plug it in, or name it: make edge-lan-link IFACE=<device>."
        )
    return adapters[0]


def _write(run: Runner, argv: list[str]) -> int:
    return run(argv, check=False).returncode


def apply(
    lan_cidr: str,
    *,
    route: bool = False,
    remove: bool = False,
    interface: str | None = None,
    run: Runner = subprocess.run,
) -> int:
    """Create or update the profile and bring it up, or remove it. Returns nmcli's exit code."""
    if shutil.which("nmcli") is None:
        raise LanLinkRefused(
            "ERROR: nmcli not found. "
            "WHY: the lab LAN link is a NetworkManager profile. "
            "FIX: run it from the Linux laptop; a Mac has no implementation yet."
        )
    exists = PROFILE in _read(run, "NAME", "connection", "show")
    if remove:
        return _write(run, ["nmcli", "connection", "delete", PROFILE]) if exists else 0

    settings = profile_settings(lan_cidr, route)
    adapter = _adapter(run, interface)
    if exists:
        first = ["nmcli", "connection", "modify", PROFILE, "connection.interface-name", adapter, *settings]
    else:
        first = ["nmcli", "connection", "add", "type", "ethernet", "con-name", PROFILE, "ifname", adapter, *settings]
    return _write(run, first) or _write(run, ["nmcli", "connection", "up", PROFILE])
