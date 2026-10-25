"""The lab edge's SSOT block (NET-005, ADR-075 D1).

`networking.edge` describes the RPi4 as the lab's edge: `uplink` is the one
block that changes per site, and `lab_wifi` is the lab's own network, which does
not. Every value here is plaintext. What would locate a site or let a stranger
on it claim the lab's paid access (SSIDs, PSKs, the uplink adapter's MAC, the
portal's domains) lives in SOPS under the same path, so this file also fails if
one of those keys appears in a committed values file.

The DHCP reservations' MACs moved out of `provision-rpi4.yml` into
`networking.nodes.<node>.mac` with this block, so the playbook carries no
address of its own.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
VALUES = REPO / "infra" / "config" / "values"
PLAYBOOK = REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml"

UPLINK_KINDS = {"wifi_open", "wifi_psk", "ethernet"}
# The 2.4 GHz channels each regulatory domain allows. hostapd refuses to start
# on a channel its `country_code` forbids, so an out-of-set value is a dead AP.
CHANNELS_BY_REGDOMAIN = {"US": range(1, 12), "ES": range(1, 14)}
SITE_IDENTIFYING_KEYS = {"ssid", "psk", "mac", "bssid", "portal_domains"}
MAC = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


@pytest.fixture(scope="module")
def networking() -> dict[str, Any]:
    return yaml.safe_load((VALUES / "common.yaml").read_text())["networking"]


@pytest.fixture(scope="module")
def edge(networking: dict[str, Any]) -> dict[str, Any]:
    return networking["edge"]


def _keys(tree: Any) -> set[str]:
    if not isinstance(tree, dict):
        return set()
    found = set(tree)
    for value in tree.values():
        found |= _keys(value)
    return found


def _values_of(tree: Any, key: str) -> list[Any]:
    """Every value `key` takes anywhere in a parsed YAML tree, lists included."""
    if isinstance(tree, list):
        return [value for item in tree for value in _values_of(item, key)]
    if not isinstance(tree, dict):
        return []
    found = [tree[key]] if key in tree else []
    return found + [value for child in tree.values() for value in _values_of(child, key)]


def test_the_uplink_declares_a_known_kind_and_its_site_settings(edge: dict[str, Any]) -> None:
    uplink = edge["uplink"]
    assert uplink["kind"] in UPLINK_KINDS
    assert uplink["interface"]
    assert uplink["regdomain"] in CHANNELS_BY_REGDOMAIN
    assert uplink["bandwidth"]["down_kbit"] > 0
    assert uplink["bandwidth"]["up_kbit"] > 0


def test_the_ap_channel_is_one_the_regdomain_allows(edge: dict[str, Any]) -> None:
    uplink = edge["uplink"]
    assert uplink["channel"] in CHANNELS_BY_REGDOMAIN[uplink["regdomain"]]


def test_the_lab_wifi_gateway_and_pool_sit_inside_its_cidr(edge: dict[str, Any]) -> None:
    lab = edge["lab_wifi"]
    cidr = ipaddress.ip_network(lab["cidr"])
    gateway = ipaddress.ip_address(lab["gateway"])
    start = ipaddress.ip_address(lab["dhcp_range"]["start"])
    end = ipaddress.ip_address(lab["dhcp_range"]["end"])
    assert gateway in cidr
    assert start in cidr and end in cidr and start <= end
    assert not start <= gateway <= end, "the pool would lease the AP's own address"


def test_each_lab_wifi_reservation_is_a_node_with_a_mac_and_an_address_inside_the_cidr(
    networking: dict[str, Any], edge: dict[str, Any]
) -> None:
    cidr = ipaddress.ip_network(edge["lab_wifi"]["cidr"])
    reservations = edge["lab_wifi"]["reservations"]
    assert reservations, "rpi3 has no screen: without its reservation, Kuma's route loses its address"
    for name in reservations:
        node = networking["nodes"][name]
        assert MAC.match(node["mac"]), name
        assert ipaddress.ip_address(node["lan_ip"]) in cidr, name


def test_the_lab_cidr_is_clear_of_the_lan_and_the_tailnet(networking: dict[str, Any], edge: dict[str, Any]) -> None:
    lab = ipaddress.ip_network(edge["lab_wifi"]["cidr"])
    for other in (networking["lan_cidr"], networking["tailscale_cidr"]):
        assert not lab.overlaps(ipaddress.ip_network(other)), other


def test_the_rpi4s_wifi_address_is_the_lab_gateway(networking: dict[str, Any], edge: dict[str, Any]) -> None:
    assert networking["nodes"]["rpi4"]["wifi_lan_ip"] == edge["lab_wifi"]["gateway"]


def test_no_trust_list_names_the_lab_cidr(networking: dict[str, Any], edge: dict[str, Any]) -> None:
    """No trust list names the lab network on purpose (ADR-041, AC3).

    This does not show that lab clients are untrusted. The RFC 1918 supernets in
    `trusted_cidrs` predate this edge and contain the lab CIDR, so what keeps a lab
    client from the LAN is the edge's forward drops, tested with the firewall.
    What this forbids is an entry that names the lab network itself, or a range
    inside it, and an advertised route to it: trust granted to the personal
    devices deliberately.
    """
    lab = ipaddress.ip_network(edge["lab_wifi"]["cidr"])
    for entry in networking["trusted_cidrs"]:
        assert not ipaddress.ip_network(entry).subnet_of(lab), entry
    # Parsed, not matched by line: a block list would put its second route on a
    # line a regex never reads.
    routes = _values_of(yaml.safe_load(PLAYBOOK.read_text()), "tailscale_advertise_routes")
    assert routes
    advertised = " ".join(str(route) for route in routes)
    assert "lab_wifi" not in advertised
    assert edge["lab_wifi"]["cidr"] not in advertised


@pytest.mark.parametrize("values", sorted(VALUES.glob("*.yaml")), ids=lambda p: p.name)
def test_no_site_identifying_key_is_committed_under_the_edge(values: Path) -> None:
    tree = yaml.safe_load(values.read_text()) or {}
    edge = (tree.get("networking") or {}).get("edge") or {}
    assert not _keys(edge) & SITE_IDENTIFYING_KEYS, f"{values.name}: these belong in SOPS"


def test_the_rpi4_playbook_carries_no_literal_mac_or_ip() -> None:
    text = PLAYBOOK.read_text()
    assert not re.search(r"\b[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}\b", text), "MACs belong in networking.nodes.<node>.mac"
    assert not re.search(r"\b\d{1,3}(\.\d{1,3}){3}\b", text), "addresses belong in common.yaml"


def test_every_homelab_reservation_reads_its_mac_from_the_ssot(networking: dict[str, Any]) -> None:
    text = PLAYBOOK.read_text()
    for name in ("ace1", "ace2", "beelink", "jetson"):
        assert MAC.match(networking["nodes"][name]["mac"]), name
        assert f"config.networking.nodes.{name}.mac" in text, name
