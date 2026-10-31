"""The uplink, rendered from the site profile (NET-005 AC6, AC9, ADR-075 D2 and D3).

- The uplink's DHCP lease supplies an address and nothing else. netplan's
  `use-routes: false` also turns off networkd's `UseGateway=`, which defaults to
  `UseRoutes=`, so a drop-in turns the gateway back on. netplan cannot express it.
  The drop-in only applies if its directory is named after the `.network` file
  netplan generates for the interface. A wrong name leaves the RPi4 with no default
  route and no error, so one test asks netplan itself which file it generates.
- `eth0` is the recovery path, since the RPi4 has no screen, so every kind renders it.
- The AP interface belongs to a networkd unit of its own (PR 5). A netplan-generated
  `.network` file for it would sort first and override that unit.
- The adapter is pinned by its permanent MAC from SOPS and renamed, so the profile
  never carries the kernel's MAC-derived name.
"""

from __future__ import annotations

import configparser
import os
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env


def _netplan_or_skip() -> None:
    """The two tests that ask netplan itself. In CI a missing netplan is a failure,
    or a runner-image change would turn both into a quiet skip; elsewhere it is a
    skip, which means CANNOT CHECK, never OK."""
    if shutil.which("netplan") is None:
        if os.environ.get("CI"):
            pytest.fail("netplan not on PATH in CI: the drop-in's directory and the validate command went unchecked")
        pytest.skip("CANNOT CHECK: netplan is not installed")


REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TEMPLATES = ROLE / "templates"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))[
    "networking"
]
EDGE = NETWORKING["edge"]

KINDS = ("wifi_open", "wifi_psk", "ethernet")
LAN = "eth0"
LAN_CIDR = f"{NETWORKING['nodes']['rpi4']['lan_ip']}/24"
UPLINK = EDGE["uplink"]["interface"]
AP = EDGE["lab_wifi"]["interface"]
# Stand-ins for the SOPS values. A locally administered MAC, so it names no adapter.
SECRETS = {
    "gateway_uplink_mac": "02:00:5e:10:00:01",
    "gateway_uplink_ssid": "site-ssid",
    "gateway_uplink_psk": "site-passphrase",
}


def _vars(kind: str, **overrides: Any) -> dict[str, Any]:
    return {
        "gateway_interface": LAN,
        "gateway_lan_cidr": LAN_CIDR,
        "gateway_uplink_interface": UPLINK,
        "gateway_ap_interface": AP,
        "gateway_uplink_kind": kind,
        "gateway_uplink_regdomain": EDGE["uplink"]["regdomain"],
        "gateway_uplink_band": "",
        **SECRETS,
        **overrides,
    }


def _render(template: str, kind: str = "wifi_open", **overrides: Any) -> str:
    env = ansible_env(str(TEMPLATES), trim_blocks=True, keep_trailing_newline=True)
    return env.get_template(template).render(**_vars(kind, **overrides))


def _netplan(kind: str, **overrides: Any) -> dict[str, Any]:
    return yaml.safe_load(_render("netplan-edge.yaml.j2", kind, **overrides))["network"]


def _generate(kind: str, root: Path) -> Path:
    """Run `netplan generate` on the rendered file; returns where it writes networkd's units."""
    (root / "etc" / "netplan").mkdir(parents=True)
    rendered = root / "etc" / "netplan" / "10-kubelab-edge.yaml"
    rendered.write_text(_render("netplan-edge.yaml.j2", kind), encoding="utf-8")
    rendered.chmod(0o600)
    subprocess.run(["netplan", "generate", "--root-dir", str(root)], check=True, capture_output=True)
    return root / "run" / "systemd" / "network"


def _uplink(kind: str) -> dict[str, Any]:
    return _netplan(kind)["ethernets" if kind == "ethernet" else "wifis"][UPLINK]


def _ini(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read_string(text)
    return parser


def _task_writing(dest: str) -> dict[str, Any]:
    for task in TASKS:
        args = task.get("template") or task.get("ansible.builtin.template") or {}
        if args.get("dest") == dest:
            return args
    raise AssertionError(f"no template task writes {dest}")


@pytest.mark.parametrize("kind", KINDS)
def test_the_lease_supplies_an_address_and_nothing_else(kind: str) -> None:
    """Option 121 routes and the site's DNS, NTP, domains and hostname are refused (AC9)."""
    uplink = _uplink(kind)
    assert uplink["dhcp4"] is True
    assert uplink["dhcp4-overrides"] == {
        "use-routes": False,
        "use-dns": False,
        "use-ntp": False,
        "use-domains": False,
        "use-hostname": False,
        "send-hostname": False,
    }
    assert uplink["dhcp-identifier"] == "mac"


@pytest.mark.parametrize("kind", KINDS)
def test_the_uplink_has_no_ipv6(kind: str) -> None:
    uplink = _uplink(kind)
    assert uplink["dhcp6"] is False
    assert uplink["accept-ra"] is False
    assert uplink["link-local"] == []


@pytest.mark.parametrize("kind", KINDS)
def test_the_lan_renders_static_for_every_kind(kind: str) -> None:
    """The RPi4 has no screen: no profile may take away the recovery path."""
    lan = _netplan(kind)["ethernets"][LAN]
    assert lan["addresses"] == [LAN_CIDR]
    assert not lan.get("dhcp4")


@pytest.mark.parametrize("kind", KINDS)
def test_the_lan_keeps_its_address_and_route_without_a_cable(kind: str) -> None:
    """networkd configures no address on a link without a carrier, by default.

    T4 of the hard-reset test measured what that costs (#2732): no LAN address,
    so no connected route, and LAN traffic from the tailnet left by the uplink.
    """
    assert _netplan(kind)["ethernets"][LAN]["ignore-carrier"] is True


@pytest.mark.parametrize("kind", KINDS)
def test_boot_waits_for_no_interface(kind: str) -> None:
    """netplan pulls wait-online in for each interface that is not optional.

    On the edge it rendered `-i eth0:degraded` for the LAN alone, and with the
    switch cable out that failed after two minutes (#2732). The uplink is a site's
    and the LAN a cable's, so boot waits for neither.
    """
    rendered = _netplan(kind)
    # Every device section, so a bridge or a VLAN added later is held to it too.
    interfaces = {
        name: iface for section in rendered.values() if isinstance(section, dict) for name, iface in section.items()
    }
    assert interfaces, "the guard found no interface"
    assert {name for name, iface in interfaces.items() if iface.get("optional") is not True} == set()


@pytest.mark.parametrize("kind", KINDS)
def test_netplan_configures_the_lan_without_a_carrier(kind: str, tmp_path: Path) -> None:
    """Asked of netplan itself: the key above is the one networkd reads."""
    _netplan_or_skip()
    generated = _generate(kind, tmp_path)
    network = _ini((generated / f"10-netplan-{LAN}.network").read_text(encoding="utf-8"))
    assert network["Network"]["ConfigureWithoutCarrier"] == "yes"


@pytest.mark.parametrize("kind", KINDS)
def test_the_ap_interface_is_in_no_netplan_file(kind: str) -> None:
    network = _netplan(kind)
    assert AP not in {**network.get("ethernets", {}), **network.get("wifis", {})}
    assert AP not in _render("netplan-edge.yaml.j2", kind)


def test_an_open_site_is_joined_without_a_passphrase() -> None:
    uplink = _uplink("wifi_open")
    assert uplink["access-points"] == {SECRETS["gateway_uplink_ssid"]: {}}
    assert uplink["regulatory-domain"] == EDGE["uplink"]["regdomain"]


def test_a_psk_site_is_joined_with_its_passphrase() -> None:
    uplink = _uplink("wifi_psk")
    assert uplink["access-points"] == {SECRETS["gateway_uplink_ssid"]: {"password": SECRETS["gateway_uplink_psk"]}}
    assert uplink["regulatory-domain"] == EDGE["uplink"]["regdomain"]


@pytest.mark.parametrize("band", ["5GHz", "2.4GHz"])
def test_a_site_band_pins_the_access_point(band: str) -> None:
    """A band holds the uplink off a congested one (#2875): netplan renders it as
    wpa_supplicant's freq_list."""
    ssid = SECRETS["gateway_uplink_ssid"]
    assert _netplan("wifi_open", gateway_uplink_band=band)["wifis"][UPLINK]["access-points"] == {ssid: {"band": band}}
    psk = _netplan("wifi_psk", gateway_uplink_band=band)["wifis"][UPLINK]["access-points"][ssid]
    assert psk == {"password": SECRETS["gateway_uplink_psk"], "band": band}


def test_the_site_band_is_one_netplan_knows() -> None:
    assert EDGE["uplink"]["band"] in ("", "5GHz", "2.4GHz")
    assert _passes("wifi_open", gateway_uplink_band=EDGE["uplink"]["band"])
    assert not _passes("wifi_open", gateway_uplink_band="6GHz")


def test_the_ethernet_kind_renders_no_wifi() -> None:
    assert "wifis" not in _netplan("ethernet")
    assert SECRETS["gateway_uplink_ssid"] not in _render("netplan-edge.yaml.j2", "ethernet")


def test_the_drop_in_turns_the_gateway_back_on() -> None:
    assert dict(_ini(_render("dhcp-gateway.conf.j2"))["DHCPv4"]) == {"UseGateway": "yes"}


def test_the_drop_in_sits_beside_the_network_file_netplan_generates() -> None:
    dest = "/etc/systemd/network/10-netplan-{{ gateway_uplink_interface }}.network.d/kubelab-gateway.conf"
    assert _task_writing(dest)["src"] == "dhcp-gateway.conf.j2"


@pytest.mark.parametrize("kind", KINDS)
def test_netplan_generates_the_file_the_drop_in_names(kind: str, tmp_path: Path) -> None:
    """Asked of netplan itself: the drop-in's directory is only right if this file exists."""
    _netplan_or_skip()
    generated = _generate(kind, tmp_path)
    network = _ini((generated / f"10-netplan-{UPLINK}.network").read_text(encoding="utf-8"))
    # netplan 1.x writes the legacy `[DHCP]` section, which networkd reads as DHCPv4.
    sections = [network[name] for name in ("DHCP", "DHCPv4") if network.has_section(name)]
    dhcp = {key: value for section in sections for key, value in section.items()}
    assert dhcp["UseRoutes"] == "false"
    # The drop-in is the only thing that sets it, so the gateway does not depend on
    # what netplan's defaults happen to be.
    assert "UseGateway" not in dhcp
    assert not list(generated.glob(f"*{AP}*"))


def test_the_link_file_pins_the_adapter_by_its_permanent_mac() -> None:
    link = _ini(_render("uplink.link.j2"))
    assert dict(link["Match"]) == {"PermanentMACAddress": SECRETS["gateway_uplink_mac"]}
    assert dict(link["Link"]) == {"Name": UPLINK, "MACAddressPolicy": "none"}


def _profile_check() -> list[str]:
    for task in TASKS:
        args = task.get("assert") or task.get("ansible.builtin.assert") or {}
        if "gateway_uplink_kind" in str(args.get("that")):
            return args["that"]
    raise AssertionError("no task asserts the site profile")


def _passes(kind: str, **overrides: Any) -> bool:
    env = ansible_env(str(TEMPLATES))
    return all(env.compile_expression(check)(**_vars(kind, **overrides)) for check in _profile_check())


@pytest.mark.parametrize("kind", KINDS)
def test_a_complete_profile_passes_the_check(kind: str) -> None:
    assert _passes(kind)


@pytest.mark.parametrize(
    ("kind", "missing"),
    [
        ("wifi_open", "gateway_uplink_mac"),
        ("wifi_psk", "gateway_uplink_mac"),
        ("ethernet", "gateway_uplink_mac"),
        ("wifi_open", "gateway_uplink_ssid"),
        ("wifi_psk", "gateway_uplink_ssid"),
        ("wifi_psk", "gateway_uplink_psk"),
    ],
)
def test_a_profile_missing_a_secret_its_kind_needs_fails_the_check(kind: str, missing: str) -> None:
    """The secrets are typed by the operator, so a run before they are stored must stop."""
    assert not _passes(kind, **{missing: ""})


def test_the_ethernet_kind_needs_no_ssid() -> None:
    assert _passes("ethernet", gateway_uplink_ssid="", gateway_uplink_psk="")


def test_an_unknown_kind_fails_the_check() -> None:
    assert not _passes("wifi_enterprise")


def _gateway_vars() -> dict[str, Any]:
    plays = yaml.safe_load(
        (REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml").read_text(encoding="utf-8")
    )
    for play in plays:
        for role in play.get("roles", []):
            if isinstance(role, dict) and role.get("role", "").endswith("/gateway"):
                return role["vars"]
    raise AssertionError("provision-rpi4.yml runs no gateway role")


def test_the_playbook_maps_the_profile_and_its_secrets() -> None:
    """Secrets default to empty so the role's check, not a Jinja error, names what is missing."""
    variables = _gateway_vars()
    for key in ("kind", "regdomain", "interface", "band"):
        assert variables[f"gateway_uplink_{key}"] == f"{{{{ config.networking.edge.uplink.{key} }}}}"
    for key in ("mac", "ssid", "psk"):
        assert variables[f"gateway_uplink_{key}"] == f"{{{{ secrets.networking.edge.uplink.{key} | default('') }}}}"


def test_the_validate_command_accepts_the_rendered_file_and_refuses_a_broken_one(tmp_path: Path) -> None:
    """Run the way Ansible runs `validate`: `%s` substituted, split, no shell."""
    _netplan_or_skip()
    validate = _task_writing("/etc/netplan/10-kubelab-edge.yaml")["validate"]
    good = tmp_path / "good.yaml"
    good.write_text(_render("netplan-edge.yaml.j2"), encoding="utf-8")
    bad = tmp_path / "bad.yaml"
    bad.write_text("network:\n  version: 2\n  ethernets:\n    eth0:\n      dhcp4: maybe\n", encoding="utf-8")
    for path, accepted in ((good, True), (bad, False)):
        result = subprocess.run(shlex.split(validate % path), capture_output=True, check=False)
        assert (result.returncode == 0) is accepted, result.stderr
