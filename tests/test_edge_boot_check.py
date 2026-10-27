"""After a boot, the edge says whether it brought back everything it serves.

The RPi4 is the lab's uplink, DHCP, DNS, Wi-Fi and subnet route at once, and a
power cut is the failure it meets most. The hard-reset test in
`docs/runbooks/lab-edge.md` pulls the power with everything plugged in, then
without the uplink adapter, then without the switch cable. After each boot,
`make edge-boot-check` runs the gateway role's check on the edge and prints one
line per check. For a case that took something away, the check for that thing
passes when it is missing.

The script runs under dash, with fake `systemctl`, `ip`, `ss`, `dig`,
`hostapd_cli`, `docker`, `nft` and `tailscale` that read recorded state from files.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any
from unittest import mock

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
NETWORKING = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]
SCRIPT = ROLE / "files" / "edge-boot-check.sh"
SHELL = shutil.which("dash") or "/bin/sh"
LAN, UPLINK, AP = "eth0", NETWORKING["edge"]["uplink"]["interface"], NETWORKING["edge"]["lab_wifi"]["interface"]
LAN_CIDR = NETWORKING["lan_cidr"]
# Documentation ranges (RFC 5737): none is a lab address.
LAN_ADDRESS, LEASE_ADDRESS = "192.0.2.1", "198.51.100.23"
UNITS = (
    "hostapd.service",
    "dnsmasq.service",
    "docker.service",
    "tailscaled.service",
    "kubelab-edge-liveness.timer",
    "kubelab-edge-lease-check.timer",
    "kubelab-edge-lease-check.path",
    "kubelab-edge-shaper.service",
)
LIVENESS = "kubelab-edge-liveness.service"
# The page the liveness check's failure sends, which cannot leave without the uplink:
# the unit's own OnFailure= line, with `%n` resolved the way systemd resolves it.
PAGE = (
    re.search(r"^OnFailure=(\S+)$", (ROLE / "templates" / f"{LIVENESS}.j2").read_text(), re.M)
    .group(1)
    .replace("%n", LIVENESS)
)

FAKES = {
    "sudo": '[ "$1" = -n ] && shift\nexec "$@"\n',
    "nft": '[ -f "$FAKE/ruleset" ]\n',
    "systemctl": """case "$1 $2" in
  "show -p") cat "$FAKE/show_$3_${5:-manager}" 2>/dev/null || echo 0 ;;
  "is-active --quiet") [ -f "$FAKE/active/$3" ] ;;
  "is-failed --quiet") [ "$(cat "$FAKE/activating/$3" 2>/dev/null || echo 0)" -eq 0 ] && [ -f "$FAKE/failed/$3" ] ;;
  "is-active "*)
    runs=$(cat "$FAKE/activating/$2" 2>/dev/null || echo 0)
    if [ "$runs" -gt 0 ]; then echo $((runs - 1)) >"$FAKE/activating/$2"; echo activating; else echo inactive; fi ;;
  "--failed --no-legend")
    for f in "$FAKE"/failed/*; do [ -f "$f" ] && echo "${f##*/} loaded failed failed x"; done
    true ;;
  *) exit 2 ;;
esac
""",
    "ip": """case "$2 $3" in
  "-o addr") cat "$FAKE/addr_$6" 2>/dev/null ;;
  "route show") cat "$FAKE/route_$6" 2>/dev/null ;;
esac
""",
    "hostapd_cli": 'cat "$FAKE/hostapd_$4"\n',
    "ss": 'cat "$FAKE/ss_udp_67" 2>/dev/null\n',
    "dig": 'cat "$FAKE/dig_${1#@}" 2>/dev/null\n',
    "docker": 'cat "$FAKE/docker_$4"\n',
    "tailscale": 'cat "$FAKE/tailscale.json"\n',
    "sleep": ":\n",
    "systemd-analyze": 'echo "Startup finished in 5.1s (kernel) + 20.3s (userspace) = 25.4s"\n',
}


class Edge:
    """The edge as the boot check sees it, healthy until a test takes something away."""

    def __init__(self, root: Path) -> None:
        self.fake, self.bin, self.net = root / "fake", root / "bin", root / "net"
        for directory in (self.fake / "active", self.fake / "failed", self.fake / "activating", self.bin):
            directory.mkdir(parents=True)
        for name, body in FAKES.items():
            (self.bin / name).write_text(f"#!/bin/sh\n{body}")
            (self.bin / name).chmod(0o755)
        self.write("ruleset", "")
        self.write("show_RuntimeWatchdogUSec_manager", "15s")
        self.write(f"show_OnFailure_{LIVENESS}", PAGE)
        for unit in UNITS:
            self.write(f"active/{unit}", "")
        self.write(f"hostapd_{AP}", "state=ENABLED\nphy=phy0\n")
        self.write("ss_udp_67", "UNCONN 0 0 0.0.0.0%wlan0:67 0.0.0.0:*\n")
        self.write(f"dig_{LAN_ADDRESS}", "127.0.0.1\n")
        self.write("docker_coredns", "running \n")
        self.write("docker_pihole", "running healthy\n")
        self.write(f"addr_{LAN}", f"2: {LAN}    inet {LAN_ADDRESS}/24 brd 192.0.2.255 scope global {LAN}\n")
        self.write(f"addr_{UPLINK}", f"3: {UPLINK}    inet {LEASE_ADDRESS}/24 scope global dynamic {UPLINK}\n")
        self.write(f"route_{UPLINK}", "default via 198.51.100.1 proto dhcp\n")
        self.order(ruleset=9.6, networkd=15.5)
        self.tailnet(state="Running", routes=[LAN_CIDR])
        for interface in (LAN, UPLINK, AP):
            (self.net / interface).mkdir(parents=True)
            self.write_sys(interface, "1")

    def write(self, name: str, text: str) -> None:
        (self.fake / name).write_text(text)

    def read(self, name: str) -> str:
        return (self.fake / name).read_text().strip()

    def remove(self, name: str) -> None:
        (self.fake / name).unlink()

    def write_sys(self, interface: str, carrier: str) -> None:
        (self.net / interface / "carrier").write_text(f"{carrier}\n")

    def order(self, ruleset: float, networkd: float) -> None:
        """When each unit reached the state the check reads, in seconds since boot; 0 never."""
        self.write("show_ActiveEnterTimestampMonotonic_nftables.service", f"{round(ruleset * 1e6)}\n")
        self.write("show_InactiveExitTimestampMonotonic_systemd-networkd.service", f"{round(networkd * 1e6)}\n")

    def tailnet(self, state: str, routes: list[str], allowed: tuple[str, ...] = ("100.64.0.99/32",)) -> None:
        # Indented, as `tailscale status --json` prints it.
        def array(key: str, items: Any) -> str:
            return f'    "{key}": [\n' + ",\n".join(f'      "{i}"' for i in items) + "\n    ]"

        self.write("tailscale.json", f'{{\n  "BackendState": "{state}",\n  "Self": {{\n'
                   + array("AllowedIPs", allowed) + ",\n" + array("PrimaryRoutes", routes) + "\n  }\n}\n")  # fmt: skip

    def unplug_uplink(self) -> None:
        shutil.rmtree(self.net / UPLINK)
        for name in (f"addr_{UPLINK}", f"route_{UPLINK}", "active/kubelab-edge-shaper.service"):
            self.remove(name)
        self.tailnet(state="NoState", routes=[])
        self.write(f"failed/{LIVENESS}", "")
        self.write(f"failed/{PAGE}", "")

    def unplug_lan(self) -> None:
        self.write_sys(LAN, "0")
        self.remove(f"addr_{LAN}")
        self.remove(f"dig_{LAN_ADDRESS}")

    def run(self, *args: str, expect: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "FAKE": str(self.fake),
            "EDGE_SYS_NET": str(self.net),
            "EDGE_HOSTAPD_DIR": str(self.fake),
        }
        if expect:
            env["EDGE_EXPECT"] = expect
        argv = args or (LAN, LAN_ADDRESS, UPLINK, AP, LAN_CIDR)
        return subprocess.run([SHELL, str(SCRIPT), *argv], capture_output=True, text=True, env=env, check=False)


def _failures(result: subprocess.CompletedProcess[str]) -> list[str]:
    return [line for line in result.stdout.splitlines() if line.startswith("FAIL")]


@pytest.fixture
def edge(tmp_path: Path) -> Edge:
    return Edge(tmp_path)


# ------------------------------------------------------------ everything plugged in


def test_a_healthy_boot_passes_every_check(edge: Edge) -> None:
    result = edge.run()
    assert result.returncode == 0, result.stdout
    assert not _failures(result)
    assert result.stdout.startswith("INFO Startup finished")
    assert "INFO ruleset loaded at 9.6s, systemd-networkd started at 15.5s" in result.stdout


def _stop(unit: str) -> Any:
    return lambda edge: edge.remove(f"active/{unit}")


BROKEN = {
    "ruleset not loaded": (lambda e: e.remove("ruleset"), "ruleset inet kubelab"),
    "watchdog off": (lambda e: e.write("show_RuntimeWatchdogUSec_manager", "0"), "hardware watchdog"),
    **{f"{unit} down": (_stop(unit), unit) for unit in UNITS},
    # In AP mode but not beaconing: hostapd has not enabled it.
    "AP not enabled": (lambda e: e.write(f"hostapd_{AP}", "state=DISABLED\n"), f"{AP} serves"),
    "nothing on the DHCP port": (lambda e: e.remove("ss_udp_67"), "DHCP server listening"),
    "LAN DNS silent": (lambda e: e.remove(f"dig_{LAN_ADDRESS}"), "DNS answers on the LAN"),
    # dig prints its diagnostics on stdout, so any output is not an answer.
    "LAN DNS refused": (
        lambda e: e.write(f"dig_{LAN_ADDRESS}", ";; communications error to 192.0.2.1#53: connection refused\n"),
        "DNS answers on the LAN",
    ),
    "pihole unhealthy": (lambda e: e.write("docker_pihole", "running unhealthy\n"), "container pihole"),
    "pihole still starting": (lambda e: e.write("docker_pihole", "running starting\n"), "container pihole"),
    "coredns exited": (lambda e: e.write("docker_coredns", "exited \n"), "container coredns"),
    "no LAN address": (lambda e: e.remove(f"addr_{LAN}"), "LAN address"),
    # A prefix of the declared one, so a match that stops at the address's end is not enough.
    "another LAN address": (
        lambda e: e.write(f"addr_{LAN}", f"2: {LAN}    inet {LAN_ADDRESS}7/24 scope global {LAN}\n"),
        "LAN address",
    ),
    "ruleset after networkd": (lambda e: e.order(ruleset=16.0, networkd=15.5), "loaded before systemd-networkd"),
    "ruleset never active": (lambda e: e.order(ruleset=0, networkd=15.5), "loaded before systemd-networkd"),
    "networkd never started": (lambda e: e.order(ruleset=9.6, networkd=0), "loaded before systemd-networkd"),
    "no lease": (lambda e: e.remove(f"addr_{UPLINK}"), "lease on"),
    "no default route": (lambda e: e.remove(f"route_{UPLINK}"), "default route"),
    "tailnet stopped": (lambda e: e.tailnet(state="Stopped", routes=[LAN_CIDR]), "tailnet session"),
    "LAN route not primary": (lambda e: e.tailnet(state="Running", routes=[]), "subnet route"),
    # Approved but another node is primary for it: the CIDR is in the status, not where it counts.
    "LAN route allowed, not primary": (
        lambda e: e.tailnet(state="Running", routes=[], allowed=("100.64.0.99/32", LAN_CIDR)),
        "subnet route",
    ),
    "a failed unit": (lambda e: e.write("failed/foo.service", ""), "failed units: foo.service"),
    # Only the no-uplink case expects the liveness check to have failed.
    "liveness failed with the uplink up": (
        lambda e: e.write(f"failed/{LIVENESS}", ""),
        f"failed units: {LIVENESS}",
    ),
    "a page failed with the uplink up": (lambda e: e.write(f"failed/{PAGE}", ""), f"failed units: {PAGE}"),
}


@pytest.mark.parametrize(("breakage", "line"), BROKEN.values(), ids=BROKEN.keys())
def test_each_thing_a_boot_can_lose_fails_its_own_check(edge: Edge, breakage: Any, line: str) -> None:
    breakage(edge)
    result = edge.run()
    assert result.returncode == 1
    (failure,) = _failures(result)
    assert line in failure


# ------------------------------------------------------------ a case took something


def test_without_the_uplink_adapter_the_rest_still_passes(edge: Edge) -> None:
    """The liveness check fails on a missing uplink and its page cannot leave, so
    both failures are what the case expects, and no other unit may fail."""
    edge.unplug_uplink()
    result = edge.run(expect="no-uplink")
    assert result.returncode == 0, result.stdout
    assert f"OK   uplink adapter {UPLINK}: missing, as this case expects" in result.stdout
    assert f"OK   {LIVENESS} failed on the missing uplink" in result.stdout


def test_an_uplink_that_is_there_fails_the_no_uplink_case(edge: Edge) -> None:
    edge.write(f"failed/{LIVENESS}", "")
    (failure,) = _failures(edge.run(expect="no-uplink"))
    assert "present, but this case took it away" in failure


def test_the_expected_page_is_the_one_systemd_names(edge: Edge) -> None:
    """The exemption reads the unit's OnFailure= from systemd, so a renamed notifier
    moves it too instead of failing the case on the page it expected."""
    edge.unplug_uplink()
    edge.remove(f"failed/{PAGE}")
    edge.write(f"show_OnFailure_{LIVENESS}", "kubelab-page@x.service")
    edge.write("failed/kubelab-page@x.service", "")
    result = edge.run(expect="no-uplink")
    assert result.returncode == 0, result.stdout


def test_a_missing_uplink_nobody_pages_fails(edge: Edge) -> None:
    edge.unplug_uplink()
    edge.remove(f"failed/{LIVENESS}")
    (failure,) = _failures(edge.run(expect="no-uplink"))
    assert "failed on the missing uplink" in failure


def test_a_liveness_run_under_way_is_waited_out(edge: Edge) -> None:
    """Its timer runs it every minute, and a running unit is not failed."""
    edge.unplug_uplink()
    edge.write(f"activating/{LIVENESS}", "3")
    result = edge.run(expect="no-uplink")
    assert result.returncode == 0, result.stdout
    assert edge.read(f"activating/{LIVENESS}") == "0"


def test_a_liveness_run_that_never_ends_fails_in_bounded_time(edge: Edge) -> None:
    edge.unplug_uplink()
    edge.write(f"activating/{LIVENESS}", "100")
    (failure,) = _failures(edge.run(expect="no-uplink"))
    assert "failed on the missing uplink" in failure
    assert edge.read(f"activating/{LIVENESS}") == "39"


def test_without_the_uplink_another_failed_unit_still_fails(edge: Edge) -> None:
    edge.unplug_uplink()
    edge.write("failed/dnsmasq.service", "")
    (failure,) = _failures(edge.run(expect="no-uplink"))
    assert failure == "FAIL failed units: dnsmasq.service"


def test_without_the_switch_cable_the_rest_still_passes(edge: Edge) -> None:
    edge.unplug_lan()
    result = edge.run(expect="no-lan")
    assert result.returncode == 0, result.stdout
    assert f"OK   {LAN} present without a carrier, as this case expects" in result.stdout


def test_a_cable_that_is_there_fails_the_no_lan_case(edge: Edge) -> None:
    assert _failures(edge.run(expect="no-lan")) == [f"FAIL {LAN} present without a carrier, as this case expects"]


def test_a_lan_device_that_is_gone_fails_the_no_lan_case(edge: Edge) -> None:
    """A missing cable leaves the device; a missing device is another failure."""
    edge.unplug_lan()
    shutil.rmtree(edge.net / LAN)
    assert _failures(edge.run(expect="no-lan")) == [f"FAIL {LAN} present without a carrier, as this case expects"]


@pytest.mark.parametrize("args", [(LAN,), (LAN, LAN_ADDRESS, UPLINK, AP), (LAN, LAN_ADDRESS, UPLINK, AP, LAN_CIDR, "")])
def test_usage(edge: Edge, args: tuple[str, ...]) -> None:
    assert edge.run(*args).returncode == 64


def test_an_unknown_case_is_usage(edge: Edge) -> None:
    assert edge.run(expect="no-power").returncode == 64


def test_it_prints_no_address(edge: Edge) -> None:
    """On a healthy edge, where every probe has an address to print."""
    out = edge.run().stdout
    assert LAN_ADDRESS not in out
    assert LEASE_ADDRESS not in out
    assert "127.0.0.1" not in out


# ------------------------------------------------------------------ the role


def test_the_role_installs_the_script_and_what_it_runs() -> None:
    install = [t for t in TASKS if (t.get("copy") or {}).get("src") == SCRIPT.name]
    assert [t["copy"]["dest"] for t in install] == ["{{ gateway_boot_check_path }}"]
    assert install[0]["copy"]["mode"] == "0755"


# The units the boot check reads that another role on the edge starts.
UNIT_OF_ROLE = {"docker": "docker", "tailscale": "tailscaled"}


def test_it_checks_the_units_and_containers_the_roles_start() -> None:
    """A renamed unit or container would leave its check looking at nothing."""
    roles = {role: yaml.safe_load((ROLE.parent / role / "tasks" / "main.yml").read_text()) for role in UNIT_OF_ROLE}
    started = {
        t["systemd"]["name"]
        for tasks in (TASKS, *roles.values())
        for t in tasks
        if "systemd" in t and "name" in t["systemd"]
    }
    text = SCRIPT.read_text()
    for unit in ("hostapd", "dnsmasq", *UNIT_OF_ROLE.values(), *(u for u in UNITS if u.startswith("kubelab-edge"))):
        assert unit in started or f"{unit}.service" in started or unit.removesuffix(".service") in started
        assert unit in text
    compose = (REPO / "infra/ansible/roles/coredns/templates/docker-compose.yml.j2").read_text()
    assert set(re.findall(r"container_name: (\S+)", compose)) == {"coredns", "pihole"}


# ----------------------------------------------------------- the operator's side


def test_the_command_passes_the_ssot_values() -> None:
    from toolkit.features.edge_status import BOOT_CHECK_PATH, LAN_INTERFACE, boot_check_command

    (name,) = [n for n, node in NETWORKING["nodes"].items() if "gateway" in (node.get("ansible_groups") or [])]
    node = NETWORKING["nodes"][name]
    command = boot_check_command(NETWORKING)
    assert command[0] == "ssh"
    assert f"HostKeyAlias={node['tailscale_ip']}" in command
    assert command[-7:] == [
        f"{NETWORKING['ssh_users']['homelab']}@{node['lan_ip']}",
        BOOT_CHECK_PATH,
        LAN_INTERFACE,
        node["lan_ip"],
        UPLINK,
        AP,
        LAN_CIDR,
    ]
    assert BOOT_CHECK_PATH == DEFAULTS["gateway_boot_check_path"]
    playbook = (REPO / "infra/ansible/playbooks/provision-rpi4.yml").read_text()
    assert f'gateway_interface: "{LAN_INTERFACE}"' in playbook


def test_a_case_and_the_tailnet_path_reach_the_command() -> None:
    from toolkit.features.edge_status import BOOT_CHECK_PATH, boot_check_command

    (node,) = [n for n in NETWORKING["nodes"].values() if "gateway" in (n.get("ansible_groups") or [])]
    command = boot_check_command(NETWORKING, "no-lan", "tailnet")
    at = command.index(BOOT_CHECK_PATH)
    target = f"{NETWORKING['ssh_users']['homelab']}@{node['tailscale_ip']}"
    assert command[at - 2 : at] == [target, "EDGE_EXPECT=no-lan"]


@pytest.mark.parametrize(
    ("argv", "code"),
    [([], 0), (["--case", "no-uplink"], 1), (["--case", "no-power"], 64), (["--via", "wifi"], 64)],
)
def test_the_command_exits_with_the_checks_code(argv: list[str], code: int) -> None:
    from typer.testing import CliRunner

    from toolkit.cli.infra import app

    with mock.patch("toolkit.features.edge_status.subprocess.run") as run:
        run.return_value = subprocess.CompletedProcess([], code)
        result = CliRunner().invoke(app, ["edge", "boot-check", *argv])
    assert result.exit_code == code
    assert run.called is (code != 64)


def test_the_makefile_target_calls_the_command() -> None:
    makefile = (REPO / "Makefile").read_text()
    target = re.search(r"^edge-boot-check:.*\n((?:\t.*\n)+)", makefile, re.M)
    assert target, "no edge-boot-check target"
    assert "infra edge boot-check $(if $(CASE),--case $(CASE)) $(if $(VIA),--via $(VIA))" in target.group(1)
