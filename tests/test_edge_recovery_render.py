"""The edge recovers itself where a reboot can (NET-005 AC13, ADR-075 D5).

The RPi4's radio firmware can halt, after a weak client or an eighth station, and
only a reboot brings it back (raspberrypi/firmware#1403). Two mechanisms:

- systemd arms the BCM2835 hardware watchdog, so a hung PID 1 reboots the edge.
  15 seconds is the hardware's ceiling.
- A liveness timer checks the lab Wi-Fi and escalates in order: after a few misses
  in a row it reloads the radio's driver and restarts hostapd, and if the AP is
  still down at the next check it reboots. A state file caps the reboots per hour,
  so a radio that never comes back cannot loop the edge.

The uplink is checked too, but never rebooted for. A present adapter with no lease
is the site (down, out of range, a changed passphrase), which a reboot cannot fix,
and the reboot would cost rpi3 its Wi-Fi and the homelab its route. An adapter
that disappeared gets its driver reloaded once; an unplugged one looks the same,
so no more than that.

The escalation runs the real script under dash, with fake `hostapd_cli`,
`modprobe` and `systemctl` and a fake sysfs, using the values the role renders.
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
HANDLERS: list[dict[str, Any]] = yaml.safe_load((ROLE / "handlers" / "main.yml").read_text())
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
EDGE = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]["edge"]
SCRIPT = ROLE / "files" / "edge-liveness.sh"
SERVICE = "kubelab-edge-liveness.service"
TIMER = "kubelab-edge-liveness.timer"
WATCHDOG = "/etc/systemd/system.conf.d/watchdog.conf"
AP = EDGE["lab_wifi"]["interface"]
UPLINK = EDGE["uplink"]["interface"]
AP_DRIVER = DEFAULTS["gateway_ap_driver"]
# brcmfmac is held by its vendor module on the RPi4's 6.8 kernel (measured
# 2026-10-25: `brcmfmac 1 brcmfmac_wcc`), so removing it alone fails.
HOLDER = "brcmfmac_wcc"
UPLINK_DRIVER = "rtw88_8822bu"
IFINDEX = "7"
HOUR = 3600
NOW = 1_800_000_000


def _vars(**overrides: Any) -> dict[str, Any]:
    variables: dict[str, Any] = {"ansible_managed": "managed", **DEFAULTS}
    variables.update(gateway_ap_interface=AP, gateway_uplink_interface=UPLINK)
    variables.update(overrides)
    return variables


def _render(name: str, **overrides: Any) -> str:
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True, lstrip_blocks=True)
    return env.get_template(f"{name}.j2").render(**_vars(**overrides))


def _directives(text: str) -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            keys.setdefault(key.strip(), []).append(value.strip())
    return keys


def _first(predicate: Any) -> int:
    return next(i for i, task in enumerate(TASKS) if predicate(task))


def _systemd(task: dict[str, Any]) -> dict[str, Any]:
    return task.get("systemd") or task.get("ansible.builtin.systemd") or {}


def _holds(condition: Any, **variables: Any) -> bool:
    env = ansible_env(str(ROLE / "templates"))
    conditions = condition if isinstance(condition, list) else [condition]
    return all(env.compile_expression(str(c))(**variables) for c in conditions)


def _environment() -> dict[str, str]:
    """The `Environment=` the role renders into the unit: the ladder's numbers."""
    return dict(item.split("=", 1) for item in _directives(_render(SERVICE)).get("Environment", []))


# --------------------------------------------------------------- the watchdog


def test_the_watchdog_drop_in_arms_the_hardware_watchdog() -> None:
    text = _render("watchdog.conf")
    assert "[Manager]" in text.splitlines()
    assert _directives(text)["RuntimeWatchdogSec"] == ["15s"]


def test_the_role_writes_the_drop_in_and_re_executes_systemd() -> None:
    """PID 1 reads system.conf.d when it re-executes, not on a daemon-reload."""
    task = TASKS[_first(lambda task: (task.get("template") or {}).get("dest") == WATCHDOG)]
    assert task["template"]["src"] == "watchdog.conf.j2"
    (handler,) = [h for h in HANDLERS if h["name"] == task["notify"]]
    assert _systemd(handler) == {"daemon_reexec": True}


def test_the_drop_in_directory_exists_before_the_drop_in() -> None:
    directory = _first(lambda task: (task.get("file") or {}).get("path") == str(Path(WATCHDOG).parent))
    assert TASKS[directory]["file"]["state"] == "directory"
    assert directory < _first(lambda task: (task.get("template") or {}).get("dest") == WATCHDOG)


@pytest.mark.parametrize(("seconds", "accepted"), [(15, True), (1, True), (16, False), (0, False)])
def test_the_timeout_cannot_exceed_the_hardware_ceiling(seconds: int, accepted: bool) -> None:
    """0 turns the watchdog off; the BCM2835 counts at most 15 s, and a kernel that does
    not extend that in software refuses a longer timeout."""
    check = TASKS[_first(lambda task: "gateway_watchdog_sec" in str(task.get("assert")))]
    assert _holds(check["assert"]["that"], gateway_watchdog_sec=seconds) is accepted
    assert check["assert"]["fail_msg"].startswith("ERROR:")


# ------------------------------------------------------------------ the units


def test_the_service_runs_the_installed_script_on_the_edges_interfaces() -> None:
    (command,) = _directives(_render(SERVICE))["ExecStart"]
    assert shlex.split(command) == [DEFAULTS["gateway_liveness_path"], AP, AP_DRIVER, UPLINK]
    install = TASKS[_first(lambda task: (task.get("copy") or {}).get("src") == SCRIPT.name)]
    assert install["copy"]["dest"] == "{{ gateway_liveness_path }}"
    assert install["copy"]["mode"] == "0755"


def test_the_ladder_forgets_on_a_reboot_and_the_reboot_count_does_not() -> None:
    """The misses and the reload marker live in /run, so a reboot starts the ladder
    again; the reboots are counted in /var/lib, so a reboot cannot reset the cap."""
    keys = _directives(_render(SERVICE))
    assert keys["RuntimeDirectory"] == ["kubelab-edge-liveness"]
    assert keys["RuntimeDirectoryPreserve"] == ["yes"]
    assert keys["StateDirectory"] == ["kubelab-edge-liveness"]


def test_the_service_shares_tmp_with_hostapd() -> None:
    """hostapd_cli binds its reply socket under /tmp, and hostapd answers to that path
    in its own mount namespace: a private or read-only /tmp gets no reply."""
    keys = _directives(_render(SERVICE))
    assert "PrivateTmp" not in keys
    assert keys.get("ProtectSystem", ["no"]) != ["strict"]


def test_a_failure_pages_and_a_clean_run_closes_it() -> None:
    keys = _directives(_render(SERVICE))
    assert keys["Type"] == ["oneshot"]
    assert keys["OnFailure"] == ["kubelab-notify@%n.service"]
    assert keys["OnSuccess"] == ["kubelab-notify-recovered@%n.service"]


def test_the_timer_waits_after_a_boot_and_never_overlaps_a_run() -> None:
    """A boot or a re-provision restarts hostapd and networkd; the first check comes
    after both have had time to settle."""
    keys = _directives(_render(TIMER))
    assert keys["OnActiveSec"] == ["5min"]
    assert keys["OnUnitInactiveSec"] == ["1min"]
    assert keys["Unit"] == [SERVICE]
    assert keys["WantedBy"] == ["timers.target"]


def test_the_timer_is_started_and_check_mode_skips_a_unit_it_has_not_written() -> None:
    units = _first(lambda task: SERVICE in str(task.get("loop")))
    assert TIMER in TASKS[units]["loop"]
    register = TASKS[units]["register"]
    timer = TASKS[_first(lambda task: _systemd(task).get("name") == TIMER)]
    assert _systemd(timer)["enabled"] is True
    assert _systemd(timer)["state"] == f"{{{{ 'restarted' if {register} is changed else 'started' }}}}"
    new, same = {"changed": True}, {"changed": False}
    assert not _holds(timer["when"], ansible_check_mode=True, **{register: new})
    assert _holds(timer["when"], ansible_check_mode=True, **{register: same})
    assert _holds(timer["when"], ansible_check_mode=False, **{register: new})


def test_the_ladder_has_a_grace_and_a_cap() -> None:
    env = _environment()
    assert int(env["EDGE_LIVENESS_GRACE"]) >= 2, "one miss is a hostapd restart during a provision"
    assert int(env["EDGE_LIVENESS_MAX_REBOOTS"]) >= 1


def test_the_units_pass_systemd_analyze_verify(tmp_path: Path) -> None:
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is not installed")
    (tmp_path / SERVICE).write_text(_render(SERVICE, gateway_liveness_path="/bin/true"))
    (tmp_path / TIMER).write_text(_render(TIMER))
    for stub in ("kubelab-notify@.service", "kubelab-notify-recovered@.service"):
        (tmp_path / stub).write_text("[Service]\nType=oneshot\nExecStart=/bin/true\n")
    proc = subprocess.run(
        ["systemd-analyze", "verify", "--man=no", str(tmp_path / SERVICE), str(tmp_path / TIMER)],
        capture_output=True,
        text=True,
        env={"SYSTEMD_UNIT_PATH": f"{tmp_path}:", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# ------------------------------------------------------------- the escalation

FAKES = {
    "hostapd_cli": 'echo "hostapd_cli $*" >>"$FAKE/calls"\ncat "$FAKE/hostapd_status" 2>/dev/null\n',
    "modprobe": 'echo "modprobe $*" >>"$FAKE/calls"\n',
    "systemctl": 'echo "systemctl $*" >>"$FAKE/calls"\n',
}


@dataclass
class Edge:
    """A fake edge: sysfs, lease and hostapd state, and the commands the script ran."""

    root: Path
    calls: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in ("fake", "bin", "net", "module", "leases", "run", "state"):
            (self.root / name).mkdir()
        for name, body in FAKES.items():
            (self.root / "bin" / name).write_text(f"#!/bin/sh\n{body}")
            (self.root / "bin" / name).chmod(0o755)
        (self.root / "module" / AP_DRIVER / "holders" / HOLDER).mkdir(parents=True)
        self.ap(serving=True)
        self.uplink(present=True, lease=True)

    def ap(self, *, serving: bool) -> None:
        (self.root / "net" / AP).mkdir(exist_ok=True)
        (self.root / "net" / AP / "operstate").write_text("up\n" if serving else "down\n")
        state = "ENABLED" if serving else "DISABLED"
        (self.root / "fake" / "hostapd_status").write_text(f"state={state}\nphy=phy0\nfreq=2437\n")

    def uplink(self, *, present: bool, lease: bool = True) -> None:
        device = self.root / "net" / UPLINK
        if not present:
            shutil.rmtree(device, ignore_errors=True)
            return
        (device / "device" / "driver").mkdir(parents=True, exist_ok=True)
        module = device / "device" / "driver" / "module"
        if not module.is_symlink():
            module.symlink_to(f"../../../../module/{UPLINK_DRIVER}")
        (device / "ifindex").write_text(f"{IFINDEX}\n")
        lease_file = self.root / "leases" / IFINDEX
        if lease:
            lease_file.write_text("# This is private data. Do not parse.\nADDRESS=192.0.2.10\n")
        else:
            lease_file.unlink(missing_ok=True)

    def reboots(self, *times: int) -> None:
        (self.root / "state" / "reboots").write_text("".join(f"{t}\n" for t in times))

    def run(self, now: int = NOW) -> subprocess.CompletedProcess[str]:
        calls = self.root / "fake" / "calls"
        calls.unlink(missing_ok=True)
        env = {
            **_environment(),
            "PATH": f"{self.root / 'bin'}:/usr/bin:/bin",
            "FAKE": str(self.root / "fake"),
            "EDGE_SYS_NET": str(self.root / "net"),
            "EDGE_SYS_MODULE": str(self.root / "module"),
            "EDGE_LEASES_DIR": str(self.root / "leases"),
            "RUNTIME_DIRECTORY": str(self.root / "run"),
            "STATE_DIRECTORY": str(self.root / "state"),
            "EDGE_NOW": str(now),
            "EDGE_SETTLE": "0",
        }
        result = subprocess.run(
            [SHELL, str(SCRIPT), AP, AP_DRIVER, UPLINK], capture_output=True, text=True, env=env, check=False
        )
        self.calls = [c for c in (calls.read_text().splitlines() if calls.exists() else []) if "status" not in c]
        return result

    def recorded_reboots(self) -> list[str]:
        path = self.root / "state" / "reboots"
        return path.read_text().split() if path.exists() else []


# The RPi4 runs dash; a bash-only construct must fail here.
SHELL = shutil.which("dash") or "/bin/sh"
GRACE = int(_environment()["EDGE_LIVENESS_GRACE"])
MAX_REBOOTS = int(_environment()["EDGE_LIVENESS_MAX_REBOOTS"])
RELOAD_AP = [f"modprobe -r {HOLDER} {AP_DRIVER}", f"modprobe {AP_DRIVER}", "systemctl restart hostapd"]
REBOOT = ["systemctl reboot"]


@pytest.fixture
def edge(tmp_path: Path) -> Edge:
    return Edge(tmp_path)


def _miss(edge: Edge, times: int) -> subprocess.CompletedProcess[str]:
    result = edge.run()
    for _ in range(times - 1):
        result = edge.run()
    return result


def test_a_healthy_edge_does_nothing(edge: Edge) -> None:
    result = edge.run()
    assert result.returncode == 0, result.stderr
    assert edge.calls == []


def test_misses_below_the_grace_do_nothing(edge: Edge) -> None:
    """A provision restarts hostapd; one miss must never reload the radio."""
    edge.ap(serving=False)
    for _ in range(GRACE - 1):
        result = edge.run()
        assert result.returncode == 0, result.stderr
        assert edge.calls == []


def test_the_grace_th_miss_reloads_the_driver_and_restarts_hostapd(edge: Edge) -> None:
    edge.ap(serving=False)
    result = _miss(edge, GRACE)
    assert result.returncode == 1
    assert edge.calls == RELOAD_AP
    assert edge.recorded_reboots() == []


def test_the_next_miss_after_the_reload_reboots(edge: Edge) -> None:
    edge.ap(serving=False)
    _miss(edge, GRACE)
    result = edge.run()
    assert result.returncode == 1
    assert edge.calls == REBOOT
    assert edge.recorded_reboots() == [str(NOW)]


def test_an_ap_that_disappeared_is_a_miss(edge: Edge) -> None:
    """A halted firmware can take the interface with it."""
    shutil.rmtree(edge.root / "net" / AP)
    _miss(edge, GRACE)
    assert edge.calls == RELOAD_AP


def test_hostapd_enabled_on_a_down_interface_is_a_miss(edge: Edge) -> None:
    (edge.root / "net" / AP / "operstate").write_text("down\n")
    _miss(edge, GRACE)
    assert edge.calls == RELOAD_AP


@pytest.mark.parametrize("status", ["state=DISABLED\n", "state=COUNTRY_UPDATE\n", ""])
def test_an_up_interface_whose_hostapd_is_not_enabled_is_a_miss(edge: Edge, status: str) -> None:
    """A halted firmware can leave the interface up; hostapd is what knows. No reply is
    a hostapd that is gone or hung."""
    (edge.root / "fake" / "hostapd_status").write_text(status)
    _miss(edge, GRACE)
    assert edge.calls == RELOAD_AP


def test_a_reload_that_worked_resets_the_ladder(edge: Edge) -> None:
    edge.ap(serving=False)
    _miss(edge, GRACE)
    edge.ap(serving=True)
    assert edge.run().returncode == 0
    edge.ap(serving=False)
    _miss(edge, GRACE)
    assert edge.calls == RELOAD_AP, "a new failure starts at the reload again"


def test_the_cap_holds_the_reboot(edge: Edge) -> None:
    edge.reboots(*(NOW - 60 * (i + 1) for i in range(MAX_REBOOTS)))
    edge.ap(serving=False)
    _miss(edge, GRACE)
    result = edge.run()
    assert result.returncode == 1
    assert edge.calls == []
    assert "reboot" in result.stderr


def test_reboots_older_than_an_hour_do_not_count(edge: Edge) -> None:
    edge.reboots(*(NOW - HOUR - 60 * (i + 1) for i in range(MAX_REBOOTS)))
    edge.ap(serving=False)
    _miss(edge, GRACE)
    edge.run()
    assert edge.calls == REBOOT
    assert edge.recorded_reboots() == [str(NOW)], "an expired entry is pruned"


def test_a_reboot_ahead_of_the_clock_still_counts(edge: Edge) -> None:
    """The RPi4 has no RTC and boots with a stale clock until NTP answers, which a dead
    uplink keeps from happening. A reboot recorded 'in the future' is a clock that went
    back, and counting it is the side that cannot loop."""
    edge.reboots(*(NOW + 600 * (i + 1) for i in range(MAX_REBOOTS)))
    edge.ap(serving=False)
    _miss(edge, GRACE)
    edge.run()
    assert edge.calls == []


def test_an_uplink_without_a_lease_is_reported_never_rebooted(edge: Edge) -> None:
    edge.uplink(present=True, lease=False)
    for _ in range(GRACE + 3):
        result = edge.run()
    assert result.returncode == 1
    assert "lease" in result.stderr
    assert edge.calls == []


def test_an_uplink_that_disappeared_gets_one_driver_reload_and_no_reboot(edge: Edge) -> None:
    edge.run()  # seen once, so the driver is known
    edge.uplink(present=False)
    result = _miss(edge, GRACE)
    assert result.returncode == 1
    assert edge.calls == [f"modprobe -r {UPLINK_DRIVER}", f"modprobe {UPLINK_DRIVER}"]
    for _ in range(3):
        edge.run()
        assert edge.calls == []


def test_an_uplink_never_seen_is_reported_without_a_reload(edge: Edge) -> None:
    edge.uplink(present=False)
    result = _miss(edge, GRACE)
    assert result.returncode == 1
    assert edge.calls == []


def test_the_uplink_and_the_ap_escalate_apart(edge: Edge) -> None:
    """A dead site must not move the AP's ladder, nor the AP's the uplink's."""
    edge.uplink(present=True, lease=False)
    edge.ap(serving=False)
    _miss(edge, GRACE)
    assert edge.calls == RELOAD_AP
