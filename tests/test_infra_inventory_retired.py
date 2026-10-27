"""The infra suite does not reach for a node declared `retired`.

`tests/infra` enumerates nodes from the hand-kept `inventories/homelab.yml`,
not from the generator, so retiring a node in `common.yaml` left it in every
SSH, disk and ping check. The two files name hosts differently (`kubelab-jet1`
for `networking.nodes.jetson`); the address is what links them.
"""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from tests.infra import fixtures
from toolkit.features.generator_ansible import AnsibleGenerator

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
    if not retired:
        # A node's return is one flag, so an empty set is a valid state, not a broken fixture.
        pytest.skip("no node is retired today; the cases above cover the mechanism")

    assert not [n.name for n in nodes if n.host in retired]


ADDRESS_KEYS = ("tailscale_ip", "tailscale_dns", "lan_ip", "public_ip")
NETWORKING = fixtures._COMMON["networking"]
# Every declaration that carries an address, so every block a `retired` flag could land on.
DECLARATIONS = [
    *(("nodes", key) for key in NETWORKING.get("nodes", {})),
    *((key,) for key, block in NETWORKING.items() if isinstance(block, dict) and any(a in block for a in ADDRESS_KEYS)),
]


def _block(networking: dict, path: tuple[str, ...]) -> dict:
    for key in path:
        networking = networking[key]
    return networking


def _generated_hosts(networking: dict) -> set[str]:
    inventory = AnsibleGenerator()._build_inventory(networking)
    return {host for group in inventory["all"]["children"].values() for host in group.get("hosts") or {}}


@pytest.mark.parametrize("path", DECLARATIONS, ids=".".join)
def test_the_suite_and_the_generator_agree_on_what_retired_removes(path: tuple[str, ...]) -> None:
    """The fixture is the second reader of the flag. Where it honours `retired` and
    the generator does not, a node drops out of the live suite while it is still
    provisioned, silently; the reverse leaves the suite dialling a node nothing
    provisions. Either way the two lists disagree about which machines exist."""
    present = copy.deepcopy(NETWORKING)
    _block(present, path).pop("retired", None)
    flagged = copy.deepcopy(present)
    _block(flagged, path)["retired"] = True

    generator_drops = bool(_generated_hosts(present) - _generated_hosts(flagged))
    suite_drops = bool(fixtures.retired_addresses(flagged) - fixtures.retired_addresses(present))

    assert suite_drops == generator_drops, (
        f"networking.{'.'.join(path)}: `retired` removes it from the "
        f"{'suite' if suite_drops else 'generated inventory'} only"
    )
