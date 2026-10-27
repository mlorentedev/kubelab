"""The infra suite does not reach for a node declared `retired`.

`tests/infra` enumerates nodes from the hand-kept `inventories/homelab.yml`,
not from the generator, so retiring a node in `common.yaml` left it in every
SSH, disk and ping check. The two files name hosts differently (`kubelab-jet1`
for `networking.nodes.jetson`); the address is what links them.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.infra import fixtures

LIVE = "100.64.0.201"
GONE = "100.64.0.202"


def _write_inventory(path: Path) -> Path:
    inventory = {
        "all": {
            "children": {
                "lan_nodes": {"hosts": {"kubelab-live": {"ansible_host": LIVE}}},
                "compute_nodes": {"hosts": {"kubelab-gone": {"ansible_host": GONE}}},
            }
        }
    }
    path.write_text(yaml.safe_dump(inventory), encoding="utf-8")
    return path


def test_a_host_at_a_retired_address_is_skipped(tmp_path: Path) -> None:
    networking = {"nodes": {"live": {"tailscale_ip": LIVE}, "gone": {"tailscale_ip": GONE, "retired": True}}}

    nodes = fixtures.load_inventory(_write_inventory(tmp_path / "hosts.yml"), networking=networking)

    assert [n.name for n in nodes] == ["kubelab-live"]


def test_without_the_flag_every_host_is_kept(tmp_path: Path) -> None:
    networking = {"nodes": {"live": {"tailscale_ip": LIVE}, "gone": {"tailscale_ip": GONE}}}

    nodes = fixtures.load_inventory(_write_inventory(tmp_path / "hosts.yml"), networking=networking)

    assert sorted(n.name for n in nodes) == ["kubelab-gone", "kubelab-live"]


def test_the_committed_inventory_yields_no_retired_node() -> None:
    """Against the real files: what makes `make test-infra` stop dialling the node."""
    nodes = fixtures.load_inventory()
    assert nodes, "the committed inventory produced no node: the check below would be vacuous"
    retired = fixtures.retired_addresses(fixtures._COMMON["networking"])
    assert retired, "fixture assumption: some node is retired"

    assert not [n.name for n in nodes if n.host in retired]
