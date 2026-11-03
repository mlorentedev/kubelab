"""The lab's edge is declared always-on (#3037, ADR-075).

`location` decides the backup timer, the R2 watcher's window, the Uptime Kuma
`on-demand` tag and the platform manifest. rpi4 became the edge in ADR-075 but
kept `on-demand`, so it backed up hourly on the branch meant for nodes that run
in short bursts, and its monitors were muted as if it were allowed to be off.
A node that routes the lab cannot be on-demand, so the group decides it.
"""

from __future__ import annotations

import pathlib

import yaml

COMMON = pathlib.Path(__file__).resolve().parent.parent / "infra" / "config" / "values" / "common.yaml"
EDGE_GROUP = "gateway"


def test_every_gateway_node_is_always_on() -> None:
    nodes = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["networking"]["nodes"]
    edges = {name: node for name, node in nodes.items() if EDGE_GROUP in node.get("ansible_groups", [])}
    assert edges, f"no node is in the {EDGE_GROUP!r} group; the guard would pass on nothing"
    wrong = {name: node.get("location") for name, node in edges.items() if node.get("location") != "always-on"}
    assert not wrong, f"an edge node must declare location: always-on: {wrong}"
