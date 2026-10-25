"""The edge's forward and input drops are complete on their own (NET-005 AC3, ADR-075 D3).

Tailscale's `ts-forward` and Docker's chains accept forwarded traffic before ufw's
rules, so nothing ufw says about forwarding holds on the RPi4. `inet kubelab` is the
only forward control, and these tests judge it alone: they render the template and
run packets through its chains with first-match semantics, taking nothing from ufw.

The evaluator understands only the matchers the template uses and fails on any
other token, so the template cannot grow a rule these tests silently misread.

The ruleset also loads over the LAN session that provisions it (D7), so the tests
that keep `eth0` open are the ones that keep the operator able to fix a mistake.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "infra" / "ansible" / "roles" / "gateway" / "templates"
EDGE = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]["edge"]

LAN = "eth0"
UPLINK = EDGE["uplink"]["interface"]
AP = EDGE["lab_wifi"]["interface"]
# Interfaces the forward path can reach besides the LAN and the AP. Docker names its
# bridges by network id, so a drop that listed them would miss the next one.
OTHER_OUTPUTS = ("docker0", "br-433906a29055", "tailscale0")


def _render() -> str:
    env = ansible_env(str(TEMPLATES), trim_blocks=True, keep_trailing_newline=True)
    return env.get_template("nftables.conf.j2").render(
        gateway_interface=LAN, gateway_uplink_interface=UPLINK, gateway_ap_interface=AP
    )


def _chains(text: str) -> dict[str, tuple[str, list[str]]]:
    """Each chain's policy and its rules, comments and blank lines dropped."""
    chains = {}
    for name, body in re.findall(r"chain (\w+) \{(.*?)\n\s*\}", text, re.S):
        lines = [line.split("#")[0].strip() for line in body.splitlines()]
        lines = [line for line in lines if line]
        header = re.search(r"policy (\w+);", lines[0])
        assert header, f"chain {name} declares no policy"
        chains[name] = (header.group(1), lines[1:])
    return chains


def _matches(pattern: str, name: str) -> bool:
    return name.startswith(pattern[:-1]) if pattern.endswith("*") else name == pattern


def _verdict(chain: tuple[str, list[str]], **packet: Any) -> str:
    """First-match verdict of `chain` for `packet` (iif, oif, state, proto, sport, dport)."""
    policy, rules = chain
    for rule in rules:
        tokens, matched, verdict, i = shlex.split(rule), True, None, 0
        while i < len(tokens):
            token = tokens[i]
            if token in ("iifname", "oifname"):
                matched &= _matches(tokens[i + 1], packet.get("iif" if token == "iifname" else "oif", ""))
                i += 2
            elif token == "ct" and tokens[i + 1] == "state":
                matched &= packet.get("state", "new") in tokens[i + 2].split(",")
                i += 3
            elif token in ("udp", "tcp") and tokens[i + 1] in ("sport", "dport"):
                matched &= packet.get("proto") == token and packet.get(tokens[i + 1]) == int(tokens[i + 2])
                i += 3
            elif token in ("accept", "drop", "masquerade") and i == len(tokens) - 1:
                verdict, i = token, i + 1
            else:
                raise AssertionError(f"the evaluator does not understand {token!r} in {rule!r}")
        assert verdict, f"rule without a verdict: {rule!r}"
        if matched:
            return verdict
    return policy


@pytest.fixture(scope="module")
def chains() -> dict[str, tuple[str, list[str]]]:
    return _chains(_render())


def test_the_ruleset_never_flushes_what_docker_ufw_and_tailscale_own() -> None:
    assert "flush ruleset" not in _render().replace("NEVER use 'flush ruleset'", "")


def test_interfaces_are_matched_by_name_so_the_uplink_rules_load_before_it_exists() -> None:
    assert not re.search(r"\b(iif|oif)\s", _render())


def test_the_table_covers_ipv4_and_ipv6_and_replaces_itself_on_reload() -> None:
    """`inet`, or IPv6 is unfiltered. Without the delete, a reload appends to the live
    chains, so a rule removed from the file would stay loaded."""
    lines = [line.strip() for line in _render().splitlines()]
    definition = lines.index("table inet kubelab {")
    assert lines.index("delete table inet kubelab") < definition
    assert lines.index("table inet kubelab") < lines.index("delete table inet kubelab")


@pytest.mark.parametrize(
    ("name", "header"),
    [
        ("input", "type filter hook input priority filter;"),
        ("forward", "type filter hook forward priority filter;"),
        ("postrouting", "type nat hook postrouting priority srcnat;"),
    ],
)
def test_each_chain_is_attached_where_its_rules_mean_something(name: str, header: str) -> None:
    """A chain on the wrong hook loads cleanly and filters nothing."""
    body = re.search(rf"chain {name} \{{(.*?)\n\s*\}}", _render(), re.S)
    assert body, name
    first = next(line.strip() for line in body.group(1).splitlines() if line.strip())
    assert first.startswith(header), first


@pytest.mark.parametrize("name", ["input", "forward"])
def test_the_filter_chains_accept_by_default_so_a_mistake_cannot_lock_out_the_lan(chains, name) -> None:
    assert chains[name][0] == "accept"


@pytest.mark.parametrize("iif", [LAN, AP, "tailscale0"])
def test_the_inside_interfaces_still_reach_the_host(chains, iif) -> None:
    assert _verdict(chains["input"], iif=iif, proto="tcp", dport=22) == "accept"


@pytest.mark.parametrize(
    "packet",
    [
        {"proto": "tcp", "dport": 22},
        {"proto": "tcp", "dport": 443},
        {"proto": "udp", "dport": 53},
        {"proto": "udp", "dport": 41641},
        {"proto": "udp", "sport": 67, "dport": 68, "state": "invalid"},
        {"proto": "tcp", "dport": 22, "state": "untracked"},
    ],
    ids=["ssh", "https", "dns", "tailscale", "invalid-dhcp", "untracked"],
)
def test_the_host_accepts_nothing_new_from_the_uplink(chains, packet) -> None:
    assert _verdict(chains["input"], iif=UPLINK, **packet) == "drop"


@pytest.mark.parametrize("state", ["established", "related"])
def test_the_host_still_gets_replies_on_the_uplink(chains, state) -> None:
    assert _verdict(chains["input"], iif=UPLINK, state=state, proto="tcp", sport=443) == "accept"


def test_the_uplink_lease_can_renew(chains) -> None:
    assert _verdict(chains["input"], iif=UPLINK, proto="udp", sport=67, dport=68) == "accept"


@pytest.mark.parametrize(("sport", "dport"), [(53, 68), (67, 69)], ids=["not-from-a-server", "not-to-a-client"])
def test_the_dhcp_exception_admits_server_to_client_only(chains, sport, dport) -> None:
    assert _verdict(chains["input"], iif=UPLINK, proto="udp", sport=sport, dport=dport) == "drop"


@pytest.mark.parametrize("oif", [LAN, AP, *OTHER_OUTPUTS])
def test_nothing_new_is_forwarded_from_the_uplink(chains, oif) -> None:
    """Covers Docker-published ports too: DNAT happens before routing, so they are forwarded."""
    assert _verdict(chains["forward"], iif=UPLINK, oif=oif, proto="udp", dport=53) == "drop"
    assert _verdict(chains["forward"], iif=UPLINK, oif=oif, state="established", proto="tcp") == "accept"


@pytest.mark.parametrize("state", ["new", "established"])
@pytest.mark.parametrize(("iif", "oif"), [(AP, LAN), (LAN, AP)], ids=["ap-to-lan", "lan-to-ap"])
def test_the_lab_wifi_and_the_homelab_lan_do_not_route_to_each_other(chains, iif, oif, state) -> None:
    assert _verdict(chains["forward"], iif=iif, oif=oif, state=state, proto="tcp", dport=22) == "drop"


@pytest.mark.parametrize("iif", [LAN, AP])
def test_the_inside_networks_still_reach_the_internet(chains, iif) -> None:
    assert _verdict(chains["forward"], iif=iif, oif=UPLINK, proto="tcp", dport=443) == "accept"
    assert _verdict(chains["postrouting"], oif=UPLINK) == "masquerade"


@pytest.mark.parametrize("oif", [LAN, AP, "tailscale0"])
def test_only_the_uplink_is_masqueraded(chains, oif) -> None:
    assert _verdict(chains["postrouting"], oif=oif) == "accept"


def test_the_masquerade_follows_the_profile_not_a_literal() -> None:
    """The old defaults named `enx*` and `wlan0`, interfaces the uplink drops never covered."""
    role = REPO / "infra" / "ansible" / "roles" / "gateway"
    defaults = yaml.safe_load((role / "defaults" / "main.yml").read_text())
    assert defaults["gateway_uplink_interface"] == UPLINK
    assert "enx" not in (role / "defaults" / "main.yml").read_text()
    plays = yaml.safe_load((REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml").read_text())
    gateway = next(
        role["vars"] for play in plays for role in play.get("roles", []) if str(role.get("role")).endswith("/gateway")
    )
    assert gateway["gateway_uplink_interface"] == "{{ config.networking.edge.uplink.interface }}"
