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
# The uplink adapter's device unit, whose start job the boot waits on (#2794).
DEVICE = f"sys-subsystem-net-devices-{UPLINK}.device"
GRACE = DEFAULTS["gateway_liveness_grace"]
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
  "list-jobs --no-legend") cat "$FAKE/jobs" 2>/dev/null; true ;;
  # Starting while jobs are queued, degraded once finished with a failed unit.
  "is-system-running ")
    if [ -f "$FAKE/system" ]; then
      head -n 1 "$FAKE/system"
      if [ "$(wc -l < "$FAKE/system")" -gt 1 ]; then sed -i 1d "$FAKE/system"; fi
    elif [ -f "$FAKE/jobs" ]; then echo starting
    elif ls "$FAKE"/failed/* >/dev/null 2>&1; then echo degraded
    else echo running; fi ;;
  *) exit 2 ;;
esac
""",
    "ip": """case "$2 $3" in
  "-o addr") cat "$FAKE/addr_$6" 2>/dev/null ;;
  "route show") if [ "$4" = exact ]; then cat "$FAKE/route_exact_$7"; else cat "$FAKE/route_$6"; fi 2>/dev/null ;;
esac
""",
    "hostapd_cli": 'cat "$FAKE/hostapd_$4"\n',
    "ss": 'cat "$FAKE/ss_udp_67" 2>/dev/null\n',
    "dig": 'cat "$FAKE/dig_${1#@}" 2>/dev/null\n',
    "docker": 'case "$3" in *PortBindings*) cat "$FAKE/ports_$4" ;; *) cat "$FAKE/docker_$4" ;; esac\n',
    "tailscale": 'cat "$FAKE/tailscale.json"\n',
    "sleep": ":\n",
    # The liveness timer's next run, in microseconds since boot, as busctl prints it.
    "busctl": 'cat "$FAKE/next_elapse" 2>/dev/null || echo "t 0"\n',
    # Before the boot finishes, `systemd-analyze time` fails with systemd's own words on
    # stderr; analyze_error stands for any other failure.
    "systemd-analyze": """if [ -f "$FAKE/jobs" ]; then
  echo "Bootup is not yet finished (org.freedesktop.systemd1.Manager.FinishTimestampMonotonic=0)." >&2
  exit 1
fi
if [ -f "$FAKE/analyze_error" ]; then cat "$FAKE/analyze_error" >&2; exit 1; fi
echo "Startup finished in 5.1s (kernel) + 20.3s (userspace) = 25.4s"
""",
}


class Edge:
    """The edge as the boot check sees it, healthy until a test takes something away."""

    def __init__(self, root: Path) -> None:
        self.fake, self.bin, self.net = root / "fake", root / "bin", root / "net"
        self.liveness, self.uptime = root / "liveness", root / "uptime"
        for directory in (
            self.fake / "active",
            self.fake / "failed",
            self.fake / "activating",
            self.bin,
            self.liveness,
        ):
            directory.mkdir(parents=True)
        for name, body in FAKES.items():
            (self.bin / name).write_text(f"#!/bin/sh\n{body}")
            (self.bin / name).chmod(0o755)
        self.write("ruleset", "")
        self.write("show_RuntimeWatchdogUSec_manager", "15s")
        self.write("show_DefaultDeviceTimeoutUSec_manager", "1min 30s\n")
        self.write(f"show_JobRunningTimeoutUSec_{DEVICE}", "10s\n")
        self.write(f"show_OnFailure_{LIVENESS}", PAGE)
        self.write(f"show_Environment_{LIVENESS}", f"KUBELAB_NOTIFY_SEVERITY=page EDGE_LIVENESS_GRACE={GRACE}\n")
        self.booted(minutes=15)
        for unit in UNITS:
            self.write(f"active/{unit}", "")
        self.write(f"hostapd_{AP}", "state=ENABLED\nphy=phy0\n")
        self.write("ss_udp_67", "UNCONN 0 0 0.0.0.0%wlan0:67 0.0.0.0:*\n")
        self.write(f"dig_{LAN_ADDRESS}", "127.0.0.1\n")
        self.write("docker_coredns", "running \n")
        self.write("docker_pihole", "running healthy\n")
        for container in ("coredns", "pihole"):
            self.write(f"ports_{container}", "3:3\n")
        self.write(f"addr_{LAN}", f"2: {LAN}    inet {LAN_ADDRESS}/24 brd 192.0.2.255 scope global {LAN}\n")
        self.write(f"addr_{UPLINK}", f"3: {UPLINK}    inet {LEASE_ADDRESS}/24 scope global dynamic {UPLINK}\n")
        self.write(f"route_{UPLINK}", "default via 198.51.100.1 proto dhcp\n")
        self.write(f"route_exact_{LAN}", f"{LAN_CIDR} proto kernel scope link src {LAN_ADDRESS}\n")
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

    def order(self, ruleset: float, networkd: float, network: float = 16.2) -> None:
        """When each unit reached the state the check reads, in seconds since boot; 0 never."""
        self.write("show_ActiveEnterTimestampMonotonic_nftables.service", f"{round(ruleset * 1e6)}\n")
        self.write("show_InactiveExitTimestampMonotonic_systemd-networkd.service", f"{round(networkd * 1e6)}\n")
        self.write("show_ActiveEnterTimestampMonotonic_network.target", f"{round(network * 1e6)}\n")

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

    def misses(self, count: int) -> None:
        """The uplink misses the liveness check has counted in a row this boot."""
        (self.liveness / "uplink.misses").write_text(f"{count}\n")

    def booted(self, minutes: float, next_run: float = 0) -> None:
        """Minutes since boot, and when the liveness timer runs next, in minutes since boot."""
        self.uptime.write_text(f"{minutes * 60:.2f} 1000.00\n")
        self.write("next_elapse", f"t {round(next_run * 60e6)}\n")

    def unplug_lan(self) -> None:
        """networkd keeps the address without a carrier (#2732); the kernel marks its route."""
        self.write_sys(LAN, "0")
        self.write(f"route_exact_{LAN}", f"{LAN_CIDR} proto kernel scope link src {LAN_ADDRESS} linkdown\n")

    def run(self, *args: str, expect: str | None = None) -> subprocess.CompletedProcess[str]:
        env = {
            "PATH": f"{self.bin}:/usr/bin:/bin",
            "FAKE": str(self.fake),
            "EDGE_SYS_NET": str(self.net),
            "EDGE_HOSTAPD_DIR": str(self.fake),
            "EDGE_LIVENESS_DIR": str(self.liveness),
            "EDGE_UPTIME": str(self.uptime),
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
    assert "OK   boot finished" in result.stdout.splitlines()
    assert "INFO ruleset loaded at 9.6s, systemd-networkd started at 15.5s, network.target reached at 16.2s" in (
        result.stdout.splitlines()
    )
    assert f"OK   wait for {UPLINK} at boot bounded (10s; systemd's default 1min 30s)" in result.stdout.splitlines()
    assert f"OK   {LAN} has a carrier" in result.stdout.splitlines()


def test_a_route_line_that_ends_at_its_prefix_still_counts(edge: Edge) -> None:
    """The prefix is matched as a field, so it need not be followed by anything."""
    edge.write(f"route_exact_{LAN}", f"{LAN_CIDR}\n")
    assert not _failures(edge.run())


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
    "coredns exited": (lambda e: e.write("docker_coredns", "exited \n"), "container coredns up"),
    # Running and healthy, with no port in effect: the state #2732 left CoreDNS in.
    "coredns on no network": (lambda e: e.write("ports_coredns", "3:0\n"), "container coredns publishes"),
    "pihole on no network": (lambda e: e.write("ports_pihole", "3:0\n"), "container pihole publishes"),
    "coredns gone": (lambda e: e.remove("ports_coredns"), "container coredns publishes"),
    # No mapping at all is a compose that lost its ports, not a container with none to publish.
    "coredns publishes nothing": (lambda e: e.write("ports_coredns", "0:0\n"), "container coredns publishes"),
    "no LAN route": (lambda e: e.remove(f"route_exact_{LAN}"), "route to"),
    "a route for another prefix": (
        lambda e: e.write(f"route_exact_{LAN}", f"172.16.10.0/24 proto kernel scope link src {LAN_ADDRESS}\n"),
        "route to",
    ),
    # The address, its route and the DNS answer on it all hold without a cable
    # (#2732), so only the carrier says the switch is there (#2800).
    "switch cable out": (lambda e: e.unplug_lan(), f"{LAN} has a carrier"),
    "no LAN address": (lambda e: e.remove(f"addr_{LAN}"), "LAN address"),
    # A prefix of the declared one, so a match that stops at the address's end is not enough.
    "another LAN address": (
        lambda e: e.write(f"addr_{LAN}", f"2: {LAN}    inet {LAN_ADDRESS}7/24 scope global {LAN}\n"),
        "LAN address",
    ),
    "ruleset after networkd": (lambda e: e.order(ruleset=16.0, networkd=15.5), "loaded before systemd-networkd"),
    "ruleset never active": (lambda e: e.order(ruleset=0, networkd=15.5), "loaded before systemd-networkd"),
    "networkd never started": (lambda e: e.order(ruleset=9.6, networkd=0), "loaded before systemd-networkd"),
    # The drop-in did not apply: a missing adapter holds network.target for 90 s (#2794).
    "adapter wait at systemd's default": (
        lambda e: e.write(f"show_JobRunningTimeoutUSec_{DEVICE}", "1min 30s\n"),
        f"wait for {UPLINK} at boot bounded",
    ),
    "adapter wait unbounded": (
        lambda e: e.write(f"show_JobRunningTimeoutUSec_{DEVICE}", "infinity\n"),
        f"wait for {UPLINK} at boot bounded",
    ),
    "adapter wait unreadable": (lambda e: e.remove(f"show_JobRunningTimeoutUSec_{DEVICE}"), "at boot bounded"),
    # Compared as durations: a wait longer than the default, or the default spelled
    # another way, is not a bound.
    "adapter wait past systemd's default": (
        lambda e: e.write(f"show_JobRunningTimeoutUSec_{DEVICE}", "2min\n"),
        f"wait for {UPLINK} at boot bounded",
    ),
    "adapter wait at the default, written another way": (
        lambda e: e.write(f"show_JobRunningTimeoutUSec_{DEVICE}", "90s\n"),
        f"wait for {UPLINK} at boot bounded",
    ),
    "systemd's default unreadable": (
        lambda e: e.remove("show_DefaultDeviceTimeoutUSec_manager"),
        f"wait for {UPLINK} at boot bounded",
    ),
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


# ------------------------------------------------------- what a boot does not judge

# A scheduled job that failed during the outage the case caused, and its page, which
# could not leave either: node-backup-ship cannot reach R2 without the uplink.
SHIP = "node-backup-ship.service"
SHIP_PAGE = f"kubelab-notify@{SHIP}.service"


def _scheduled_run_failed(edge: Edge, unit: str = SHIP, page: str = SHIP_PAGE, page_failed: bool = True) -> None:
    edge.write(f"show_TriggeredBy_{unit}", f"{unit.removesuffix('.service')}.timer")
    edge.write(f"show_OnFailure_{unit}", page)
    edge.write(f"failed/{unit}", "")
    if page and page_failed:
        edge.write(f"failed/{page}", "")


def test_a_failed_scheduled_run_its_page_reported_is_not_failed(edge: Edge) -> None:
    """A run a timer started is not something the boot brings back, and its own page
    reports it; the operator ruled it out of the boot's verdict (#2661, B14 T3)."""
    _scheduled_run_failed(edge, page_failed=False)
    result = edge.run()
    assert result.returncode == 0, result.stdout
    assert f"INFO failed scheduled runs, each paged: {SHIP}" in result.stdout
    assert "nobody was paged" not in result.stdout


@pytest.mark.parametrize(("page", "page_failed"), [(SHIP_PAGE, True), ("", False)], ids=["page-failed", "no-page"])
def test_a_failed_scheduled_run_nobody_was_paged_for_is_named_apart(edge: Edge, page: str, page_failed: bool) -> None:
    """When the page failed too, or the unit declares none, the run reached nobody, and
    saying it was reported would be false (#2767 review)."""
    _scheduled_run_failed(edge, page=page, page_failed=page_failed)
    result = edge.run()
    assert result.returncode == 0, result.stdout
    assert f"INFO failed scheduled runs nobody was paged for: {SHIP}" in result.stdout
    assert "each paged" not in result.stdout
    assert SHIP_PAGE not in result.stdout


def test_without_the_uplink_a_failed_scheduled_run_is_reported_not_failed(edge: Edge) -> None:
    edge.unplug_uplink()
    _scheduled_run_failed(edge)
    result = edge.run(expect="no-uplink")
    assert result.returncode == 0, result.stdout


def test_a_failed_run_of_the_edges_own_timer_still_fails(edge: Edge) -> None:
    """The lease check and the liveness check are what the edge serves, timer or not."""
    unit = "kubelab-edge-lease-check.service"
    _scheduled_run_failed(edge, unit, f"kubelab-notify@{unit}.service")
    (failure,) = _failures(edge.run())
    assert failure == f"FAIL failed units: {unit} kubelab-notify@{unit}.service"


def test_a_page_that_failed_for_a_unit_no_timer_started_still_fails(edge: Edge) -> None:
    edge.write(f"show_OnFailure_{SHIP}", SHIP_PAGE)
    edge.write(f"failed/{SHIP}", "")
    (failure,) = _failures(edge.run())
    assert failure == f"FAIL failed units: {SHIP}"


def test_an_unfinished_boot_names_what_it_still_waits_for(edge: Edge) -> None:
    """`systemd-analyze time` prints nothing until the boot finishes, which left the
    first line empty after every boot without the uplink (#2675). The hand-made
    watchdog was a oneshot with no start timeout, so its job could hold the boot
    for good (lesson-653), and the check now says so."""
    edge.write("jobs", "123 tailscale-watchdog.service start running\n130 multi-user.target start waiting\n")
    edge.write("show_TimeoutStartUSec_tailscale-watchdog.service", "infinity\n")
    result = edge.run()
    assert result.stdout.splitlines()[0] == (
        "INFO boot not finished, jobs still queued: tailscale-watchdog.service multi-user.target"
    )
    assert _failures(result) == ["FAIL boot finished: held by tailscale-watchdog.service, with no start timeout"]
    assert result.returncode == 1, result.stdout


def test_a_boot_held_by_jobs_that_end_on_their_own_is_waited_for(edge: Edge) -> None:
    """A timer can join a boot that is still running, so the check names each running
    job with the timeout that ends it rather than judging the boot by the clock."""
    edge.write(
        "jobs",
        "140 node-backup-ship.service start running\n"
        "141 kubelab-edge-liveness.service start running\n"
        "130 multi-user.target start waiting\n",
    )
    edge.write("show_TimeoutStartUSec_node-backup-ship.service", "10min\n")
    edge.write("show_TimeoutStartUSec_kubelab-edge-liveness.service", "5min\n")
    result = edge.run()
    assert not _failures(result), result.stdout
    assert (
        "WAIT boot finished: not yet, running node-backup-ship.service (10min), "
        "kubelab-edge-liveness.service (5min): run the check again after the longest"
    ) in result.stdout.splitlines()
    assert result.returncode == 2, result.stdout


@pytest.mark.parametrize(
    "job",
    [
        "150 kubelab-edge-lease-check.service start waiting",
        "151 dev-sda1.device start running",
        "152 kubelab-edge-lease-check.service stop running",
    ],
)
def test_only_a_running_service_start_job_is_judged(edge: Edge, job: str) -> None:
    """A waiting job has not started, and a device or a stop has no start timeout."""
    edge.write("jobs", f"{job}\n")
    for unit in ("kubelab-edge-lease-check.service", "dev-sda1.device"):
        edge.write(f"show_TimeoutStartUSec_{unit}", "infinity\n")
    result = edge.run()
    assert not _failures(result), result.stdout
    assert (
        "WAIT boot finished: not yet, running no service start job: run the check again after the longest"
        in result.stdout
    )
    assert result.returncode == 2


def test_a_finished_boot_with_a_failed_unit_is_finished(edge: Edge) -> None:
    """`degraded` is reported only once the boot has finished; the failed unit is
    judged by its own check."""
    edge.write("system", "degraded\n")
    edge.write("failed/stray.service", "")
    result = edge.run()
    assert "OK   boot finished" in result.stdout.splitlines()
    assert _failures(result) == ["FAIL failed units: stray.service"]


@pytest.mark.parametrize("system", ["maintenance", "stopping", ""])
def test_a_system_neither_booting_nor_up_fails(edge: Edge, system: str) -> None:
    edge.write("system", f"{system}\n")
    assert _failures(edge.run()) == [f"FAIL boot finished: the system is {system or 'unknown'}"]


def test_a_boot_that_finishes_between_the_reads_is_finished(edge: Edge) -> None:
    """The jobs drain after `starting` is read: the empty table asks again."""
    edge.write("system", "starting\nrunning\n")
    edge.write("jobs", "")
    result = edge.run()
    assert "OK   boot finished" in result.stdout.splitlines()
    assert result.returncode == 0, result.stdout


def test_an_unfinished_boot_with_an_empty_table_says_none(edge: Edge) -> None:
    """The table can empty between the two reads."""
    edge.write("jobs", "")
    assert edge.run().stdout.splitlines()[0] == "INFO boot not finished, jobs still queued: none"


def test_a_startup_time_that_cannot_be_read_is_not_an_unfinished_boot(edge: Edge) -> None:
    """Only systemd's own "not yet finished" means the boot is still running; any other
    failure is reported as itself (#2767 review)."""
    edge.write("analyze_error", "Failed to connect to bus: No such file or directory\n")
    result = edge.run()
    assert result.stdout.splitlines()[0] == (
        "INFO startup time unavailable: Failed to connect to bus: No such file or directory"
    )
    assert result.returncode == 0, result.stdout


# ------------------------------------------------------------ a case took something


def test_without_the_uplink_adapter_the_rest_still_passes(edge: Edge) -> None:
    """The liveness check fails on a missing uplink and its page cannot leave, so
    both failures are what the case expects, and no other unit may fail."""
    edge.unplug_uplink()
    result = edge.run(expect="no-uplink")
    assert result.returncode == 0, result.stdout
    assert f"OK   uplink adapter {UPLINK}: missing, as this case expects" in result.stdout
    assert f"OK   {LIVENESS} failed on the missing uplink" in result.stdout


def test_without_the_uplink_adapter_an_unbounded_wait_for_it_fails(edge: Edge) -> None:
    """The case #2794 found: every check passed while network.target waited 90 s."""
    edge.unplug_uplink()
    edge.write(f"show_JobRunningTimeoutUSec_{DEVICE}", "1min 30s\n")
    result = edge.run(expect="no-uplink")
    assert result.returncode == 1
    (failure,) = _failures(result)
    assert f"wait for {UPLINK} at boot bounded (1min 30s; systemd's default 1min 30s)" in failure


def test_a_wait_shorter_than_the_default_is_bounded_in_any_unit(edge: Edge) -> None:
    edge.write(f"show_JobRunningTimeoutUSec_{DEVICE}", "1min 29.500000s\n")
    result = edge.run()
    assert result.returncode == 0, result.stdout
    assert f"OK   wait for {UPLINK} at boot bounded (1min 29.500000s; systemd's default 1min 30s)" in (
        result.stdout.splitlines()
    )


def test_the_wait_it_reads_is_the_one_the_role_bounds() -> None:
    """The device unit the check reads is the one the role's drop-in names."""
    (task,) = [t for t in TASKS if t.get("name") == "Bound the boot's wait for the uplink adapter"]
    assert task["template"]["dest"].startswith(
        "/etc/systemd/system/sys-subsystem-net-devices-{{ gateway_uplink_interface }}.device.d/"
    )
    assert 'since_boot JobRunningTimeoutUSec "sys-subsystem-net-devices-$uplink.device"' in SCRIPT.read_text()


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
    edge.misses(GRACE)
    (failure,) = _failures(edge.run(expect="no-uplink"))
    assert "failed on the missing uplink" in failure


def _inside_the_grace(edge: Edge) -> None:
    """The uplink is gone, and the liveness check has not failed on it yet, nor paged."""
    edge.unplug_uplink()
    edge.remove(f"failed/{LIVENESS}")
    edge.remove(f"failed/{PAGE}")


def test_a_missing_uplink_inside_the_grace_is_pending_not_failed(edge: Edge) -> None:
    """The liveness check tolerates GRACE misses a minute apart: judged earlier, the edge is
    behaving as designed (#2774)."""
    _inside_the_grace(edge)
    edge.misses(1)
    result = edge.run(expect="no-uplink")
    assert result.returncode == 2, result.stdout
    assert not _failures(result)
    (line,) = [line for line in result.stdout.splitlines() if line.startswith("WAIT")]
    assert f"1 of {GRACE} misses" in line and f"in about {GRACE - 1} min" in line, line


def test_before_its_first_run_the_wait_counts_the_time_to_it(edge: Edge) -> None:
    _inside_the_grace(edge)
    edge.booted(minutes=2, next_run=5)
    (line,) = [line for line in edge.run(expect="no-uplink").stdout.splitlines() if line.startswith("WAIT")]
    # Three minutes to its first run, which counts the first miss, then one a minute.
    assert f"0 of {GRACE} misses" in line and f"in about {3 + GRACE - 1} min" in line, line


def test_a_grace_it_cannot_read_is_not_waited_for(edge: Edge) -> None:
    _inside_the_grace(edge)
    edge.misses(1)
    edge.write(f"show_Environment_{LIVENESS}", "KUBELAB_NOTIFY_SEVERITY=page\n")
    (failure,) = _failures(edge.run(expect="no-uplink"))
    assert "failed on the missing uplink" in failure


def test_a_wait_does_not_hide_a_failure(edge: Edge) -> None:
    _inside_the_grace(edge)
    edge.misses(1)
    edge.write("failed/dnsmasq.service", "")
    result = edge.run(expect="no-uplink")
    assert result.returncode == 1, result.stdout
    assert _failures(result) == ["FAIL failed units: dnsmasq.service"]


def test_the_wait_reads_what_the_role_deploys() -> None:
    """The grace from the unit's own Environment=, the misses from its RuntimeDirectory=,
    and the next run from its timer, by the object path systemd escapes its name to."""
    script = SCRIPT.read_text()
    unit = (ROLE / "templates" / f"{LIVENESS}.j2").read_text()
    assert "Environment=EDGE_LIVENESS_GRACE={{ gateway_liveness_grace }}" in unit
    runtime = re.search(r"^RuntimeDirectory=(\S+)$", unit, re.M).group(1)
    assert f"EDGE_LIVENESS_DIR:-/run/{runtime}}}" in script
    liveness = (ROLE / "files" / "edge-liveness.sh").read_text()
    assert "miss uplink" in liveness
    assert "run_dir=${RUNTIME_DIRECTORY:" in liveness
    assert 'echo "$count" >"$run_dir/$1.misses"' in liveness
    timer = LIVENESS.replace(".service", ".timer")
    escaped = "".join(c if c.isalnum() else f"_{ord(c):02x}" for c in timer)
    assert f"/org/freedesktop/systemd1/unit/{escaped}" in script


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


def test_without_the_uplink_a_cable_that_is_out_still_fails(edge: Edge) -> None:
    """Only the no-lan case expects the switch to be gone."""
    edge.unplug_uplink()
    edge.unplug_lan()
    assert _failures(edge.run(expect="no-uplink")) == [f"FAIL {LAN} has a carrier"]


def test_the_no_lan_case_reads_the_carrier_once(edge: Edge) -> None:
    """The case's own line replaces the plain one, so a missing cable is not also a failure."""
    edge.unplug_lan()
    lines = edge.run(expect="no-lan").stdout.splitlines()
    assert [line for line in lines if "carrier" in line] == [f"OK   {LAN} present without a carrier, as this case expects"]


def test_a_cable_that_is_there_fails_the_no_lan_case(edge: Edge) -> None:
    assert _failures(edge.run(expect="no-lan")) == [f"FAIL {LAN} present without a carrier, as this case expects"]


@pytest.mark.parametrize(
    ("take", "check"),
    [
        (lambda e: e.remove(f"addr_{LAN}"), f"FAIL LAN address on {LAN}"),
        (lambda e: e.remove(f"route_exact_{LAN}"), f"FAIL route to {LAN_CIDR} on {LAN}"),
        (lambda e: e.remove(f"dig_{LAN_ADDRESS}"), "FAIL DNS answers on the LAN address"),
        (lambda e: e.write("ports_coredns", "3:0\n"), "FAIL container coredns publishes its ports"),
    ],
    ids=["address", "route", "dns", "coredns ports"],
)
def test_the_cable_takes_neither_the_lan_address_nor_what_rests_on_it(edge: Edge, take: Any, check: str) -> None:
    """Without the cable, #2732 lost the address, its route and CoreDNS's ports with it."""
    edge.unplug_lan()
    take(edge)
    assert _failures(edge.run(expect="no-lan")) == [check]


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
    [
        ([], 0),
        (["--case", "no-uplink"], 1),
        (["--case", "no-uplink"], 2),
        (["--case", "no-power"], 64),
        (["--via", "wifi"], 64),
    ],
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
