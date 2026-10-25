"""The edge watcher's targets are generated from `networking`, never hand-written (NET-005 AC12).

Prod probes the lab edge and the always-on nodes behind it, so that a dead
uplink, a portal that came back or a dead RPi4 reaches the operator from a
cluster that does not share their fate. Which nodes those are follows from the
SSOT: the edge is the node in the `gateway` Ansible group, and a node is behind
it when its LAN address is in the homelab LAN or the lab Wi-Fi. A list typed by
hand would keep probing the old set after a node moves.
"""

from __future__ import annotations

import pathlib

import pytest
import yaml

from toolkit.features.backup_destination import EDGE_WATCHER_TARGETS_PATH, render_edge_watcher_targets

REPO = pathlib.Path(__file__).resolve().parent.parent
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())


def _rows(text: str) -> dict[str, list[str]]:
    rows = {}
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            node, *rest = line.split()
            assert node not in rows, f"{node} is listed twice"
            rows[node] = rest
    return rows


def _copy() -> dict:
    return yaml.safe_load(yaml.safe_dump(COMMON))


def test_the_committed_targets_match_the_ssot() -> None:
    committed = (REPO / EDGE_WATCHER_TARGETS_PATH).read_text()
    assert committed == render_edge_watcher_targets(COMMON), (
        f"{EDGE_WATCHER_TARGETS_PATH} is stale. Regenerate it with `make sync-edge-watcher-targets`."
    )


def test_the_edge_and_the_always_on_nodes_behind_it_are_the_targets() -> None:
    """Today that is rpi4, the edge, and rpi3, on the lab Wi-Fi. Each row is
    `<node> <tailscale ip> <port>`, read from `networking.nodes` and the
    reachability port the R2 watcher already knocks on."""
    nodes = COMMON["networking"]["nodes"]
    port = str(COMMON["backup"]["watcher"]["reachability_port"])
    rows = _rows(render_edge_watcher_targets(COMMON))
    assert set(rows) == {"rpi3", "rpi4"}
    for node, row in rows.items():
        assert row == [nodes[node]["tailscale_ip"], port], node


def test_the_edge_is_a_target_whatever_its_class() -> None:
    mutated = _copy()
    mutated["networking"]["nodes"]["rpi4"]["location"] = "always-on"
    assert "rpi4" in _rows(render_edge_watcher_targets(mutated))
    mutated["networking"]["nodes"]["rpi4"]["location"] = "on-demand"
    assert "rpi4" in _rows(render_edge_watcher_targets(mutated))


def test_an_on_demand_node_behind_the_edge_is_not_a_target() -> None:
    """It is off whenever the operator is not working, so probing it would page nightly."""
    mutated = _copy()
    mutated["networking"]["nodes"]["rpi3"]["location"] = "on-demand"
    assert "rpi3" not in _rows(render_edge_watcher_targets(mutated))


def test_a_node_that_becomes_always_on_behind_the_edge_becomes_a_target() -> None:
    mutated = _copy()
    mutated["networking"]["nodes"]["beelink"]["location"] = "always-on"
    assert "beelink" in _rows(render_edge_watcher_targets(mutated))


def test_an_always_on_node_outside_the_edge_networks_is_not_a_target() -> None:
    """rpi3 off the lab Wi-Fi is not behind the edge, so the edge's health is not its."""
    mutated = _copy()
    mutated["networking"]["nodes"]["rpi3"]["lan_ip"] = "192.0.2.10"
    assert "rpi3" not in _rows(render_edge_watcher_targets(mutated))


def test_a_per_node_port_overrides_the_default() -> None:
    mutated = _copy()
    mutated["backup"]["watcher"]["reachability_ports"] = {"rpi4": 2222}
    rows = _rows(render_edge_watcher_targets(mutated))
    assert rows["rpi4"][1] == "2222"
    assert rows["rpi3"][1] == str(COMMON["backup"]["watcher"]["reachability_port"])


@pytest.mark.parametrize("groups", [[], ["gateway"]], ids=["no-edge", "two-edges"])
def test_anything_but_one_edge_refuses_to_render(groups: list[str]) -> None:
    """Fail closed: no edge renders a file that probes nothing behind it, and two
    leave it to the order of a dict which one the probe calls the edge."""
    mutated = _copy()
    mutated["networking"]["nodes"]["rpi4"]["ansible_groups"] = [
        g for g in mutated["networking"]["nodes"]["rpi4"]["ansible_groups"] if g != "gateway"
    ]
    mutated["networking"]["nodes"]["ace1"].setdefault("ansible_groups", [])
    mutated["networking"]["nodes"]["ace1"]["ansible_groups"] += groups
    if groups:
        mutated["networking"]["nodes"]["rpi4"]["ansible_groups"].append("gateway")
    with pytest.raises(ValueError, match="gateway"):
        render_edge_watcher_targets(mutated)


def test_a_target_without_a_tailscale_ip_refuses_to_render() -> None:
    """The probe runs in prod and reaches the edge only over the tailnet."""
    mutated = _copy()
    del mutated["networking"]["nodes"]["rpi3"]["tailscale_ip"]
    with pytest.raises(ValueError, match="rpi3.*tailscale_ip"):
        render_edge_watcher_targets(mutated)
