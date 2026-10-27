"""Ask the lab edge whether its uplink is up, behind a portal, or dead (NET-005 AC5).

The edge runs the check itself (the gateway role's `edge-status.sh`), because only
the edge sees its uplink. This side only reaches it, over the LAN rather than the
tailnet: the tailnet rides on the very uplink being reported on, so it goes down
exactly when the answer matters. The LAN address answers from the lab switch and,
through the edge, from the lab Wi-Fi.
"""

from __future__ import annotations

import subprocess
from typing import Any

from toolkit.features.k8s_connect import resolve_ssh_user

# Mirror gateway_status_path and gateway_boot_check_path in the gateway role's
# defaults; a test holds them equal.
STATUS_PATH = "/usr/local/sbin/kubelab-edge-status"
BOOT_CHECK_PATH = "/usr/local/sbin/kubelab-edge-boot-check"
# Mirrors gateway_interface in provision-rpi4.yml; a test holds them equal.
LAN_INTERFACE = "eth0"
# What a hard-reset case takes away, as the boot check's EDGE_EXPECT names it.
BOOT_CASES = ("no-uplink", "no-lan")


class EdgeNotDeclaredError(Exception):
    """networking.nodes declares no edge, or more than one."""


def _edge(networking: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    nodes = networking.get("nodes") or {}
    edges = [(name, node) for name, node in nodes.items() if "gateway" in (node.get("ansible_groups") or [])]
    if len(edges) != 1:
        names = ", ".join(name for name, _ in edges) or "none"
        raise EdgeNotDeclaredError(
            f"ERROR: expected one node in the gateway group, found {names}. "
            "WHY: the edge is the node the gateway role provisions. "
            "FIX: declare exactly one under networking.nodes with `gateway` in ansible_groups."
        )
    return edges[0]


def _ssh(networking: dict[str, Any], via: str = "lan") -> list[str]:
    """SSH to the edge over its LAN address, or its tailnet one when the LAN is the
    thing under test."""
    name, node = _edge(networking)
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "ConnectTimeout=10",
        # The workstation pinned the edge's key under its tailnet address.
        "-o",
        f"HostKeyAlias={node['tailscale_ip']}",
        f"{resolve_ssh_user(networking, name)}@{node['tailscale_ip' if via == 'tailnet' else 'lan_ip']}",
    ]


def status_command(networking: dict[str, Any]) -> list[str]:
    """The SSH command that runs the edge's status check."""
    return [*_ssh(networking), STATUS_PATH, networking["edge"]["uplink"]["interface"]]


def boot_check_command(networking: dict[str, Any], case: str | None = None, via: str = "lan") -> list[str]:
    """The SSH command that runs the edge's boot check, for the hard-reset case
    that took `case` away, or for a boot with everything plugged in."""
    _, node = _edge(networking)
    edge = networking["edge"]
    return [
        *_ssh(networking, via),
        *([f"EDGE_EXPECT={case}"] if case else []),
        BOOT_CHECK_PATH,
        LAN_INTERFACE,
        node["lan_ip"],
        edge["uplink"]["interface"],
        edge["lab_wifi"]["interface"],
        networking["lan_cidr"],
    ]


def run_status(networking: dict[str, Any]) -> int:
    """Run the check on the edge and return its exit code: 0 up, 2 portal, 3 dead,
    4 unknown.

    ssh's own failures (unreachable, refused key) come back as 255.
    """
    return subprocess.run(status_command(networking), check=False).returncode


def run_boot_check(networking: dict[str, Any], case: str | None = None, via: str = "lan") -> int:
    """Run the boot check on the edge: 0 every check passed, 1 one failed, 255 SSH."""
    return subprocess.run(boot_check_command(networking, case, via), check=False).returncode
