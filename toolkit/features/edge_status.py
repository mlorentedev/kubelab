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

# Mirrors gateway_status_path in the gateway role's defaults; a test holds them equal.
STATUS_PATH = "/usr/local/sbin/kubelab-edge-status"


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


def status_command(networking: dict[str, Any]) -> list[str]:
    """The SSH command that runs the edge's status check."""
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
        f"{resolve_ssh_user(networking, name)}@{node['lan_ip']}",
        STATUS_PATH,
        networking["edge"]["uplink"]["interface"],
    ]


def run_status(networking: dict[str, Any]) -> int:
    """Run the check on the edge and return its exit code: 0 up, 2 portal, 3 dead.

    ssh's own failures (unreachable, refused key) come back as 255.
    """
    return subprocess.run(status_command(networking), check=False).returncode
