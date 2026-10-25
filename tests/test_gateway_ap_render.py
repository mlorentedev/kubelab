"""The lab Wi-Fi AP, rendered from the SSOT and SOPS (NET-005 AC2, ADR-075 D2 and D8).

- WPA2-PSK with CCMP only. Management-frame protection and WPA3 stay off: the
  BCM43455 firmware breaks the first in AP mode and crashes on the second.
- The PSKs live in a `wpa_psk_file`, one `keyid=` line each, so a rotation can run
  both for a while and `hostapd_cli reload_wpa_psk` swaps them without dropping a
  station. hostapd reads the keyid up to the first blank and skips the blanks after
  the MAC, so a keyid is one word and a passphrase cannot start with a space.
- The AP interface takes the gateway address from a networkd unit of its own, even
  before hostapd brings the carrier up, so dnsmasq always has a subnet to serve.
- dnsmasq serves two networks. An untagged option applies to every range, so each
  network's router and DNS carry its tag.
"""

from __future__ import annotations

import base64
import configparser
import ipaddress
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TEMPLATES = ROLE / "templates"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
HANDLERS: list[dict[str, Any]] = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]
EDGE = NETWORKING["edge"]
LAB = EDGE["lab_wifi"]

LAN = "eth0"
LAN_GATEWAY = NETWORKING["nodes"]["rpi4"]["lan_ip"]
AP = LAB["interface"]
HOSTAPD_CONF = "/etc/hostapd/hostapd.conf"
PSK_FILE = "/etc/hostapd/hostapd.wpa_psk"
AP_UNIT = "/etc/systemd/network/10-kubelab-ap.network"
# Stand-ins for the SOPS values. Inner blanks on purpose: both files keep them.
SECRETS = {
    "gateway_ap_ssid": "lab wifi",
    "gateway_ap_psks": [{"keyid": "current", "psk": "lab pass phrase"}],
}


def _vars(**overrides: Any) -> dict[str, Any]:
    return {
        "gateway_interface": LAN,
        "gateway_lan_cidr": f"{LAN_GATEWAY}/24",
        "gateway_dhcp_range_start": DEFAULTS["gateway_dhcp_range_start"],
        "gateway_dhcp_range_end": DEFAULTS["gateway_dhcp_range_end"],
        "gateway_dhcp_lease": DEFAULTS["gateway_dhcp_lease"],
        "gateway_dns_servers": DEFAULTS["gateway_dns_servers"],
        "gateway_dhcp_reservations": [{"mac": "02:00:5e:10:00:02", "hostname": "kubelab-ace1", "ip": "172.16.1.2"}],
        "gateway_uplink_regdomain": EDGE["uplink"]["regdomain"],
        "gateway_ap_interface": AP,
        "gateway_ap_channel": EDGE["uplink"]["channel"],
        "gateway_ap_cidr": LAB["cidr"],
        "gateway_ap_address": LAB["gateway"],
        "gateway_ap_dhcp_range_start": LAB["dhcp_range"]["start"],
        "gateway_ap_dhcp_range_end": LAB["dhcp_range"]["end"],
        "gateway_ap_reservations": [NETWORKING["nodes"][name] for name in LAB["reservations"]],
        **SECRETS,
        **overrides,
    }


def _render(template: str, **overrides: Any) -> str:
    env = ansible_env(str(TEMPLATES), trim_blocks=True, keep_trailing_newline=True)
    return env.get_template(template).render(**_vars(**overrides))


def _lines(text: str) -> list[str]:
    return [line for line in text.splitlines() if line and not line.startswith("#")]


def _hostapd(**overrides: Any) -> dict[str, str]:
    return dict(line.split("=", 1) for line in _lines(_render("hostapd.conf.j2", **overrides)))


def _ini(text: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # systemd keys are case-sensitive
    parser.read_string(text)
    return parser


def _task(predicate: Any) -> dict[str, Any]:
    return next(task for task in TASKS if predicate(task))


def _template_writing(dest: str) -> dict[str, Any]:
    return _task(lambda task: (task.get("template") or {}).get("dest") == dest)


# --- hostapd.conf -----------------------------------------------------------------


def test_the_ap_runs_wpa2_ccmp_on_the_profile_channel() -> None:
    conf = _hostapd()
    assert {
        "interface": AP,
        "driver": "nl80211",
        "hw_mode": "g",
        "channel": str(EDGE["uplink"]["channel"]),
        "country_code": EDGE["uplink"]["regdomain"],
        "ieee80211d": "1",
        "wpa": "2",
        "wpa_key_mgmt": "WPA-PSK",
        "rsn_pairwise": "CCMP",
        "ieee80211w": "0",
    }.items() <= conf.items()


AP_SSOT_VARS = {
    "gateway_ap_channel": EDGE["uplink"]["channel"],
    "gateway_ap_cidr": LAB["cidr"],
    "gateway_ap_address": LAB["gateway"],
    "gateway_ap_dhcp_range_start": LAB["dhcp_range"]["start"],
    "gateway_ap_dhcp_range_end": LAB["dhcp_range"]["end"],
}


@pytest.mark.parametrize("name", AP_SSOT_VARS)
def test_the_role_keeps_no_copy_of_the_ap_addresses(name: str) -> None:
    """A run without the play's vars stops instead of rendering a stale subnet."""
    (check,) = [t for t in TASKS if t.get("name") == "Check the lab Wi-Fi addresses"]
    env = ansible_env(str(ROLE))

    def holds(variables: dict[str, Any]) -> bool:
        return all(
            env.from_string("{{ (" + condition + ") | bool }}").render(**variables) == "True"
            for condition in check["assert"]["that"]
        )

    assert DEFAULTS[name] == ""
    assert holds(AP_SSOT_VARS)
    assert not holds({**AP_SSOT_VARS, name: DEFAULTS[name]})


def test_the_ap_serves_802_11n() -> None:
    """Without both, 2.4 GHz falls back to 802.11g's 54 Mbit/s."""
    conf = _hostapd()
    assert conf["ieee80211n"] == "1"
    assert conf["wmm_enabled"] == "1"


def test_no_wps_no_tkip_and_no_inline_psk() -> None:
    """The PSK lives only in the PSK file, which a rotation reloads without a restart."""
    conf = _hostapd()
    assert not [key for key in conf if key.startswith("wps") or key in ("wpa_passphrase", "wpa_psk", "wpa_pairwise")]
    assert "TKIP" not in "".join(conf.values())


def test_the_ssid_is_rendered_as_stored() -> None:
    """hostapd takes `ssid=` to the end of the line, so a saved device rejoins only on the same bytes."""
    text = _render("hostapd.conf.j2", gateway_ap_ssid="Lab Wi-Fi ñ 2")
    assert "ssid=Lab Wi-Fi ñ 2" in text.splitlines()


def test_the_psk_file_is_the_one_the_role_writes() -> None:
    path = _hostapd()["wpa_psk_file"]
    assert path.startswith("/")
    assert path == PSK_FILE
    _template_writing(PSK_FILE)


def test_the_control_socket_is_where_the_reload_handler_looks() -> None:
    """`hostapd_cli reload_wpa_psk` (D8) and the station keyid read (AC10) both use it."""
    ctrl = _hostapd()["ctrl_interface"]
    reload = next(h for h in HANDLERS if "reload_wpa_psk" in str(h.get("command")))
    assert f"-p {ctrl}" in reload["command"]
    assert "-i {{ gateway_ap_interface }}" in reload["command"]


def test_only_root_reaches_the_control_socket() -> None:
    """The socket reloads PSKs and lists stations: group 0 keeps it to root."""
    assert _hostapd()["ctrl_interface_group"] == "0"


# --- the PSK file -----------------------------------------------------------------


def test_one_line_per_psk_with_a_wildcard_mac() -> None:
    psks = [{"keyid": "current", "psk": "old pass phrase"}, {"keyid": "next", "psk": "new pass phrase"}]
    assert _lines(_render("hostapd.wpa_psk.j2", gateway_ap_psks=psks)) == [
        "keyid=current 00:00:00:00:00:00 old pass phrase",
        "keyid=next 00:00:00:00:00:00 new pass phrase",
    ]


# --- the AP interface's address ---------------------------------------------------


def test_the_ap_interface_holds_the_gateway_address_without_a_carrier() -> None:
    unit = _ini(_render("10-kubelab-ap.network.j2"))
    prefix = ipaddress.ip_network(LAB["cidr"]).prefixlen
    assert dict(unit["Match"]) == {"Name": AP}
    assert unit["Network"]["Address"] == f"{LAB['gateway']}/{prefix}"
    assert unit["Network"]["ConfigureWithoutCarrier"] == "yes"
    assert unit["Network"]["LinkLocalAddressing"] == "no"
    assert unit["Network"]["IPv6AcceptRA"] == "no"
    # The AP is not the host's way out, so boot does not wait for it.
    assert unit["Link"]["RequiredForOnline"] == "no"


def test_the_ap_unit_sorts_before_anything_netplan_generates() -> None:
    """networkd applies the first matching file, and netplan names its own `10-netplan-*`."""
    _template_writing(AP_UNIT)
    assert Path(AP_UNIT).name < "10-netplan-"


# --- dnsmasq ----------------------------------------------------------------------


def _dnsmasq() -> list[str]:
    return _lines(_render("kubelab-dhcp.conf.j2"))


def _options(tag: str) -> dict[str, str]:
    prefix = f"dhcp-option=tag:{tag},option:"
    return dict(line[len(prefix) :].split(",", 1) for line in _dnsmasq() if line.startswith(prefix))


def test_dnsmasq_serves_the_lan_and_the_lab_wifi() -> None:
    assert [line for line in _dnsmasq() if line.startswith("interface=")] == [f"interface={LAN}", f"interface={AP}"]


def test_dnsmasq_starts_without_the_ap_interface() -> None:
    """`bind-interfaces` exits on a named interface that does not exist, which would take
    the homelab LAN's DHCP down with a failed radio. `bind-dynamic` only warns."""
    assert "bind-dynamic" in _dnsmasq()
    assert "bind-interfaces" not in _dnsmasq()


def test_dnsmasq_answers_for_its_networks_without_waiting() -> None:
    """It is the only DHCP server on both. Authoritative, a client whose lease it lost
    (a reboot, a re-imaged card) gets a NAK and a new lease at once, not after a timeout."""
    assert "dhcp-authoritative" in _dnsmasq()


def test_every_option_names_the_network_it_is_for() -> None:
    options = [line for line in _dnsmasq() if line.startswith("dhcp-option=")]
    assert options
    assert all(line.startswith("dhcp-option=tag:") for line in options)


def test_the_lab_wifi_range_comes_from_the_lab_cidr() -> None:
    ranges = [line for line in _dnsmasq() if line.startswith("dhcp-range=set:lab,")]
    assert len(ranges) == 1
    start, end = ranges[0].split(",")[1:3]
    assert (start, end) == (LAB["dhcp_range"]["start"], LAB["dhcp_range"]["end"])
    cidr = ipaddress.ip_network(LAB["cidr"])
    assert ipaddress.ip_address(start) in cidr
    assert ipaddress.ip_address(end) in cidr


def test_lab_clients_route_and_resolve_through_the_ap() -> None:
    """Pi-hole answers on the AP address: Docker publishes it on every address."""
    assert _options("lab") == {"router": LAB["gateway"], "dns-server": LAB["gateway"]}


def test_lan_clients_keep_their_router_and_resolvers() -> None:
    assert _options("lan") == {"router": LAN_GATEWAY, "dns-server": DEFAULTS["gateway_dns_servers"]}


def test_the_lan_range_is_tagged_too() -> None:
    ranges = [line for line in _dnsmasq() if line.startswith("dhcp-range=")]
    assert sorted(line.split(",")[0] for line in ranges) == ["dhcp-range=set:lab", "dhcp-range=set:lan"]


@pytest.mark.parametrize("name", LAB["reservations"])
def test_a_reserved_node_keeps_its_address_on_the_lab_wifi(name: str) -> None:
    """rpi3 has no screen, so a client that cannot rejoin cannot be fixed by hand."""
    node = NETWORKING["nodes"][name]
    assert f"dhcp-host={node['mac']},{node['hostname']},{node['lan_ip']}" in _dnsmasq()
    assert ipaddress.ip_address(node["lan_ip"]) in ipaddress.ip_network(LAB["cidr"])


# --- the role's checks ------------------------------------------------------------


def _check(fragment: str) -> list[str]:
    for task in TASKS:
        args = task.get("assert") or {}
        that = args.get("that")
        if fragment in str(that):
            return that if isinstance(that, list) else [that]
    raise AssertionError(f"no task asserts {fragment}")


def _passes(fragment: str, **variables: Any) -> bool:
    env = ansible_env(str(TEMPLATES))
    return all(env.compile_expression(check)(**variables) for check in _check(fragment))


def test_complete_lab_secrets_pass_the_check() -> None:
    assert _passes("gateway_ap_psks", **SECRETS)


@pytest.mark.parametrize(
    "overrides",
    [
        {"gateway_ap_ssid": "Lab Wi-Fi ñ 2"},
        {"gateway_ap_ssid": "x" * 32},
        {"gateway_ap_psks": [{"keyid": "current", "psk": "x" * 8}]},
        {"gateway_ap_psks": [{"keyid": "current", "psk": "x" * 63}]},
        {"gateway_ap_psks": [{"keyid": "k" * 31, "psk": "lab pass phrase"}]},
    ],
    ids=["utf8-ssid", "ssid-32-bytes", "psk-8", "psk-63", "keyid-31"],
)
def test_lab_secrets_at_the_limits_pass_the_check(overrides: dict[str, Any]) -> None:
    assert _passes("gateway_ap_psks", **{**SECRETS, **overrides})


@pytest.mark.parametrize(
    "overrides",
    [
        {"gateway_ap_ssid": ""},
        {"gateway_ap_psks": []},
        {"gateway_ap_psks": [{"keyid": "current", "psk": ""}]},
        {"gateway_ap_psks": [{"keyid": "current", "psk": "x" * 7}]},
        {"gateway_ap_psks": [{"keyid": "current", "psk": "x" * 64}]},
        {"gateway_ap_psks": [{"keyid": "current", "psk": " leading blank"}]},
        {"gateway_ap_psks": [{"keyid": "current", "psk": "trailing blank "}]},
        {"gateway_ap_psks": [{"keyid": "current", "psk": "trailing newline\n"}]},
        {"gateway_ap_psks": [{"keyid": "current", "psk": "tab\tinside"}]},
        {"gateway_ap_psks": [{"keyid": "two words", "psk": "lab pass phrase"}]},
        {"gateway_ap_psks": [{"keyid": "", "psk": "lab pass phrase"}]},
        {"gateway_ap_psks": [{"keyid": "current\n", "psk": "lab pass phrase"}]},
        {"gateway_ap_psks": [{"keyid": "k" * 32, "psk": "lab pass phrase"}]},
        {"gateway_ap_ssid": "x" * 33},
        {"gateway_ap_ssid": "ñ" * 17},
        {"gateway_ap_ssid": "two\nlines"},
        {"gateway_ap_ssid": "tab\there"},
    ],
    ids=[
        "no-ssid",
        "no-psk",
        "empty-psk",
        "short",
        "long",
        "leading-blank",
        "trailing-blank",
        "trailing-newline",
        "tab",
        "keyid-blank",
        "keyid-empty",
        "keyid-newline",
        "keyid-32",
        "ssid-33-bytes",
        "ssid-34-utf8-bytes",
        "ssid-newline",
        "ssid-tab",
    ],  # fmt: skip
)
def test_lab_secrets_hostapd_would_misread_fail_the_check(overrides: dict[str, Any]) -> None:
    assert not _passes("gateway_ap_psks", **{**SECRETS, **overrides})


def _cmdline(text: str) -> dict[str, Any]:
    return {"gateway_cmdline": {"content": base64.b64encode(text.encode()).decode()}}


def test_a_cmdline_without_a_regdomain_passes() -> None:
    assert _passes("ieee80211_regdom", **_cmdline("console=tty1 root=LABEL=writable rootwait\n"))


def test_a_missing_cmdline_passes() -> None:
    """slurp fails softly where the file does not exist, and leaves no content."""
    assert _passes("ieee80211_regdom", gateway_cmdline={})


@pytest.mark.parametrize("regdomain", ["ES", "US"])
def test_a_cmdline_regdomain_stops_the_run_whatever_its_value(regdomain: str) -> None:
    """kmod appends the kernel command line's module options after /etc/modprobe.d, and
    the kernel keeps the last value, so the token would override every site's profile."""
    text = f"console=tty1 root=LABEL=writable rootwait cfg80211.ieee80211_regdom={regdomain}\n"
    assert not _passes("ieee80211_regdom", **_cmdline(text))


def test_the_cmdline_is_read_from_the_boot_partition_and_may_be_missing() -> None:
    task = _task(lambda task: "slurp" in task and "gateway_cmdline" == task.get("register"))
    assert task["slurp"]["src"] == "/boot/firmware/cmdline.txt"
    assert task["failed_when"] is False


def test_the_regulatory_domain_persists_for_cfg80211() -> None:
    task = _task(lambda task: (task.get("copy") or {}).get("dest", "").startswith("/etc/modprobe.d/"))
    # modprobe reads only `*.conf` there.
    assert task["copy"]["dest"].endswith(".conf")
    env = ansible_env(str(TEMPLATES), keep_trailing_newline=True)
    rendered = env.from_string(task["copy"]["content"]).render(**_vars())
    assert rendered == f"options cfg80211 ieee80211_regdom={EDGE['uplink']['regdomain']}\n"


# --- the playbook -----------------------------------------------------------------


def _gateway_vars() -> dict[str, Any]:
    plays = yaml.safe_load((REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml").read_text())
    for play in plays:
        for role in play.get("roles", []):
            if isinstance(role, dict) and role.get("role", "").endswith("/gateway"):
                return role["vars"]
    raise AssertionError("provision-rpi4.yml runs no gateway role")


def test_the_playbook_maps_the_lab_wifi_from_the_ssot() -> None:
    variables = _gateway_vars()
    lab = "config.networking.edge.lab_wifi"
    assert variables["gateway_ap_cidr"] == f"{{{{ {lab}.cidr }}}}"
    assert variables["gateway_ap_address"] == f"{{{{ {lab}.gateway }}}}"
    assert variables["gateway_ap_dhcp_range_start"] == f"{{{{ {lab}.dhcp_range.start }}}}"
    assert variables["gateway_ap_dhcp_range_end"] == f"{{{{ {lab}.dhcp_range.end }}}}"
    assert variables["gateway_ap_channel"] == "{{ config.networking.edge.uplink.channel }}"
    assert (
        variables["gateway_ap_reservations"]
        == f"{{{{ {lab}.reservations | map('extract', config.networking.nodes) | list }}}}"
    )


def test_the_playbook_maps_the_lab_secrets_with_one_word_keyids() -> None:
    """Secrets default to empty so the role's check, not a Jinja error, names what is missing."""
    variables = _gateway_vars()
    assert variables["gateway_ap_ssid"] == "{{ secrets.networking.edge.lab_wifi.ssid | default('') }}"
    assert [entry["psk"] for entry in variables["gateway_ap_psks"]] == [
        "{{ secrets.networking.edge.lab_wifi.psk | default('') }}"
    ]
    assert all(re.fullmatch(r"[A-Za-z0-9_-]+", entry["keyid"]) for entry in variables["gateway_ap_psks"])
