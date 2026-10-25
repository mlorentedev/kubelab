"""The edge's kernel settings (NET-005 AC3, ADR-075 D3).

Rendered from `templates/99-kubelab-edge.conf.j2` and judged by the kernel's own
rules rather than by key presence:

- `rp_filter` takes the larger of `conf/all` and the interface's value, so strict on
  the uplink needs `all=0`. Ubuntu ships `all=2` in `10-network-security.conf`,
  which would make the uplink loose whatever its own key says.
- An interface copies `conf/default` when it is created and never follows it after.
  `eth0` and the AP exist before `systemd-sysctl` runs at boot, so they are named
  explicitly; `tailscale0`, `docker0` and the Docker bridges come later and take the
  default.
- The uplink may not exist when the file loads, so its keys carry systemd's `-`
  prefix (a failed write is ignored). systemd's udev rule re-applies per-interface
  keys when the device appears.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
TEMPLATES = REPO / "infra" / "ansible" / "roles" / "gateway" / "templates"
EDGE = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]["edge"]

LAN = "eth0"
UPLINK = EDGE["uplink"]["interface"]
AP = EDGE["lab_wifi"]["interface"]
LATER = "tailscale0"  # created after boot, so it takes conf/default


def _render() -> str:
    env = ansible_env(str(TEMPLATES), trim_blocks=True, keep_trailing_newline=True)
    return env.get_template("99-kubelab-edge.conf.j2").render(
        gateway_interface=LAN, gateway_uplink_interface=UPLINK, gateway_ap_interface=AP
    )


def _settings() -> dict[str, tuple[str, bool]]:
    """`key -> (value, ignore_failure)` from the rendered file."""
    found = {}
    for line in _render().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        found[key.lstrip("-")] = (value, key.startswith("-"))
    return found


def _value(key: str) -> int | None:
    entry = _settings().get(key)
    return int(entry[0]) if entry else None


def _rp_filter(iface: str) -> int:
    """What the kernel enforces: max(all, the interface's own value)."""
    own = _value(f"net.ipv4.conf.{iface}.rp_filter")
    if own is None:
        own = _value("net.ipv4.conf.default.rp_filter")
    return max(_value("net.ipv4.conf.all.rp_filter"), own)


def test_rp_filter_is_off_at_all_so_each_interface_decides() -> None:
    assert _value("net.ipv4.conf.all.rp_filter") == 0


@pytest.mark.parametrize(("iface", "expected"), [(UPLINK, 1), (LAN, 2), (AP, 2), (LATER, 2)])
def test_rp_filter_is_strict_on_the_uplink_and_loose_elsewhere(iface: str, expected: int) -> None:
    """Loose elsewhere because the subnet route over the tailnet is asymmetric."""
    assert _rp_filter(iface) == expected


@pytest.mark.parametrize("scope", ["all", "default", LAN, AP, UPLINK])
@pytest.mark.parametrize("key", ["accept_redirects", "send_redirects", "accept_source_route"])
def test_no_redirects_or_source_routing_on_ipv4(scope: str, key: str) -> None:
    """`send_redirects` is on if `all` OR the interface says so, so every scope is set."""
    assert _value(f"net.ipv4.conf.{scope}.{key}") == 0


@pytest.mark.parametrize("scope", ["all", "default"])
@pytest.mark.parametrize("key", ["accept_redirects", "accept_source_route"])
def test_no_redirects_or_source_routing_on_ipv6(scope: str, key: str) -> None:
    assert _value(f"net.ipv6.conf.{scope}.{key}") == 0


def test_the_host_answers_arp_only_for_its_own_interface() -> None:
    assert _value("net.ipv4.conf.all.arp_ignore") == 1
    assert _value("net.ipv4.conf.all.arp_announce") == 2


def test_ipv6_is_off_on_the_uplink_only() -> None:
    assert _value(f"net.ipv6.conf.{UPLINK}.disable_ipv6") == 1
    disabled = {key for key, (value, _) in _settings().items() if key.endswith(".disable_ipv6") and value == "1"}
    assert disabled == {f"net.ipv6.conf.{UPLINK}.disable_ipv6"}


def test_every_uplink_key_tolerates_a_missing_uplink() -> None:
    uplink_keys = {key: ignore for key, (_, ignore) in _settings().items() if f".{UPLINK}." in key}
    assert uplink_keys
    assert all(uplink_keys.values()), uplink_keys
