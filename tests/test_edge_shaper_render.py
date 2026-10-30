"""The uplink shaper (NET-005 AC8).

CAKE shapes the uplink in both directions, so a bulk transfer from one host does
not starve a call on another:

- egress on the uplink itself, `dual-srchost`: fairness between the hosts that send;
- ingress through an IFB device, `dual-dsthost ingress`: fairness between the hosts
  that receive, with the rate counted as it arrives;
- `nat` on both, so CAKE reads conntrack and sees the lab's hosts rather than the one
  masqueraded address.

The rates come from the site profile, already set below the measured ones, so the
queue forms here rather than in the site's equipment. The unit follows the uplink
device: the qdiscs die with it, and a replugged adapter gets them back through the
udev rule (#2766, tests/test_edge_uplink_replug.py).
"""

from __future__ import annotations

import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
UPLINK = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text(encoding="utf-8"))[
    "networking"
]["edge"]["uplink"]
UNIT = "kubelab-edge-shaper.service"
INTERFACE = UPLINK["interface"]
DEVICE = f"sys-subsystem-net-devices-{INTERFACE}.device"


def _vars(**overrides: Any) -> dict[str, Any]:
    variables: dict[str, Any] = {
        "ansible_managed": "managed",
        "gateway_uplink_interface": INTERFACE,
        "gateway_uplink_down_kbit": UPLINK["bandwidth"]["down_kbit"],
        "gateway_uplink_up_kbit": UPLINK["bandwidth"]["up_kbit"],
    }
    variables.update(overrides)
    # The IFB name is a role default derived from the uplink's; render it the same way.
    template = ansible_env(str(ROLE / "templates")).from_string(DEFAULTS["gateway_uplink_ifb"])
    variables.setdefault("gateway_uplink_ifb", template.render(**variables))
    return variables


def _render(**overrides: Any) -> str:
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True, lstrip_blocks=True)
    return env.get_template(f"{UNIT}.j2").render(**_vars(**overrides))


def _directives(text: str) -> dict[str, list[str]]:
    keys: dict[str, list[str]] = {}
    for line in text.splitlines():
        if "=" in line and not line.startswith("#"):
            key, value = line.split("=", 1)
            keys.setdefault(key, []).append(value)
    return keys


def _commands(key: str, text: str | None = None) -> list[list[str]]:
    """Each `key=` line as argv, with systemd's `-` prefix stripped."""
    return [shlex.split(value.lstrip("-")) for value in _directives(text or _render()).get(key, [])]


def _tc_qdisc(device: str, parent: str) -> list[str]:
    for argv in _commands("ExecStart"):
        if argv[1:3] == ["qdisc", "replace"] and argv[4] == device and parent in argv:
            return argv
    raise AssertionError(f"no qdisc on {device} {parent}")


def _ifb() -> str:
    return _vars()["gateway_uplink_ifb"]


def test_the_rates_come_from_the_profile() -> None:
    """`bandwidth` is already scaled below the measured rate; the role adds no factor."""
    assert UPLINK["bandwidth"]["down_kbit"] > 0
    assert UPLINK["bandwidth"]["up_kbit"] > 0


def test_egress_is_shaped_on_the_uplink_with_per_source_host_fairness() -> None:
    argv = _tc_qdisc(INTERFACE, "root")
    cake = argv[argv.index("cake") :]
    assert cake == ["cake", "bandwidth", f"{UPLINK['bandwidth']['up_kbit']}kbit", "nat", "dual-srchost"]


def test_ingress_is_shaped_on_the_ifb_with_per_destination_host_fairness() -> None:
    argv = _tc_qdisc(_ifb(), "root")
    cake = argv[argv.index("cake") :]
    expected = ["cake", "bandwidth", f"{UPLINK['bandwidth']['down_kbit']}kbit", "nat", "dual-dsthost", "ingress"]
    assert cake == expected


def test_the_uplinks_ingress_is_redirected_to_the_ifb() -> None:
    starts = _commands("ExecStart")
    assert ["/usr/sbin/tc", "qdisc", "add", "dev", INTERFACE, "handle", "ffff:", "ingress"] in starts
    redirect = [
        "/usr/sbin/tc", "filter", "add", "dev", INTERFACE, "parent", "ffff:",
        "matchall", "action", "mirred", "egress", "redirect", "dev", _ifb(),
    ]  # fmt: skip
    assert redirect in starts


def test_the_ifb_is_ready_before_traffic_is_redirected_to_it() -> None:
    """Packets redirected to a down device, or one without its qdisc, are dropped."""
    starts = _commands("ExecStart")
    add = starts.index(["/usr/sbin/ip", "link", "add", _ifb(), "type", "ifb"])
    up = starts.index(["/usr/sbin/ip", "link", "set", _ifb(), "up"])
    shaped = starts.index(_tc_qdisc(_ifb(), "root"))
    redirect = next(i for i, argv in enumerate(starts) if "mirred" in argv)
    assert add < shaped < redirect
    assert add < up < redirect


def test_a_restart_clears_what_the_last_start_left() -> None:
    """Without it a restart stacks a second redirect filter, and `ip link add` fails."""
    pre = _directives(_render()).get("ExecStartPre", [])
    assert f"-/usr/sbin/tc qdisc del dev {INTERFACE} ingress" in pre
    assert f"-/usr/sbin/ip link del {_ifb()}" in pre


def test_stopping_tolerates_a_device_that_is_already_gone() -> None:
    stops = _directives(_render())["ExecStop"]
    assert stops
    assert all(line.startswith("-") for line in stops)
    flat = [shlex.split(line[1:]) for line in stops]
    assert ["/usr/sbin/tc", "qdisc", "del", "dev", INTERFACE, "root"] in flat
    assert ["/usr/sbin/tc", "qdisc", "del", "dev", INTERFACE, "ingress"] in flat
    assert ["/usr/sbin/ip", "link", "del", _ifb()] in flat


def test_the_unit_follows_the_uplink_device() -> None:
    """Started by the udev rule, never by a link in the device's .wants/ (#2766):
    systemd follows that link whenever a start job for the device is enqueued, and
    with the adapter missing the unit failed with result `dependency` every 90 s."""
    text = _render()
    keys = _directives(text)
    assert keys["BindsTo"] == [DEVICE]
    assert keys["After"] == [DEVICE]
    assert "[Install]" not in text
    assert "WantedBy" not in keys
    assert keys["RemainAfterExit"] == ["yes"]


def test_a_failed_start_pages() -> None:
    assert _directives(_render())["OnFailure"] == ["kubelab-notify@%n.service"]


def test_a_successful_start_closes_the_incident_a_failed_one_opened() -> None:
    """#2689. `OnSuccess=` fires when a RemainAfterExit unit stops, which for a unit
    bound to the uplink is every unplug, and never when its start succeeds."""
    keys = _directives(_render())
    assert "OnSuccess" not in keys
    on_failure = keys["OnFailure"][0]
    recovery = on_failure.replace("kubelab-notify@", "kubelab-notify-recovered@")
    assert keys["ExecStartPost"] == [f"-/usr/bin/systemctl start --no-block {recovery}"]


def test_the_ifb_name_fits_the_kernels_limit() -> None:
    """IFNAMSIZ is 16 with the terminator: `ip link add` refuses a longer name."""
    assert len(_ifb()) <= 15
    assert _ifb() != INTERFACE


def test_another_profile_renders_its_own_rates() -> None:
    text = _render(gateway_uplink_down_kbit=9000, gateway_uplink_up_kbit=4000)
    assert "cake bandwidth 4000kbit nat dual-srchost" in text
    assert "cake bandwidth 9000kbit nat dual-dsthost ingress" in text


def test_the_unit_passes_systemd_analyze_verify(tmp_path: Path) -> None:
    if shutil.which("systemd-analyze") is None:
        pytest.skip("systemd-analyze is not installed")
    for binary in ("/usr/sbin/tc", "/usr/sbin/ip"):
        if not Path(binary).exists():
            pytest.skip(f"{binary} is not installed")
    (tmp_path / UNIT).write_text(_render(), encoding="utf-8")
    for notifier in ("kubelab-notify@.service", "kubelab-notify-recovered@.service"):
        (tmp_path / notifier).write_text("[Service]\nType=oneshot\nExecStart=/bin/true\n", encoding="utf-8")
    proc = subprocess.run(
        ["systemd-analyze", "verify", "--man=no", str(tmp_path / UNIT)],
        capture_output=True,
        text=True,
        env={"SYSTEMD_UNIT_PATH": f"{tmp_path}:", "PATH": "/usr/bin:/bin"},
        check=False,
    )
    assert proc.returncode == 0, proc.stderr


# ------------------------------------------------------------------- the role


def _first(predicate: Any) -> int:
    return next(i for i, task in enumerate(TASKS) if predicate(task))


def _systemd(task: dict[str, Any]) -> dict[str, Any]:
    return task.get("systemd") or task.get("ansible.builtin.systemd") or {}


def test_the_rates_are_checked_before_the_unit_is_written() -> None:
    """CAKE reads a zero bandwidth as unlimited: an empty profile would shape nothing."""
    check = _first(lambda task: "gateway_uplink_down_kbit" in str(task.get("assert")))
    that = " ".join(task for task in TASKS[check]["assert"]["that"])
    assert "gateway_uplink_down_kbit | int > 0" in that
    assert "gateway_uplink_up_kbit | int > 0" in that
    unit = _first(lambda task: (task.get("template") or {}).get("dest") == f"/etc/systemd/system/{UNIT}")
    assert check < unit


def test_the_shaper_is_started_only_on_a_present_uplink() -> None:
    """Starting it on a missing device would fail the run."""
    started = _first(lambda task: _systemd(task).get("name") == UNIT and "state" in _systemd(task))
    present, absent = {"stat": {"exists": True}}, {"stat": {"exists": False}}
    same = {"changed": False}
    assert _holds(
        TASKS[started]["when"], ansible_check_mode=False, gateway_uplink_sysfs=present, gateway_shaper_unit=same
    )
    assert not _holds(
        TASKS[started]["when"], ansible_check_mode=False, gateway_uplink_sysfs=absent, gateway_shaper_unit=same
    )
    rename_check = _first(lambda task: "gateway_uplink_sysfs" in str(task.get("assert")))
    assert rename_check < started


def test_a_changed_unit_restarts_the_shaper() -> None:
    unit = _first(lambda task: (task.get("template") or {}).get("dest") == f"/etc/systemd/system/{UNIT}")
    started = _first(lambda task: _systemd(task).get("name") == UNIT and "state" in _systemd(task))
    register = TASKS[unit]["register"]
    state = _systemd(TASKS[started])["state"]
    assert state == f"{{{{ 'restarted' if {register} is changed else 'started' }}}}"
    assert _systemd(TASKS[started]).get("daemon_reload")


def _holds(condition: Any, **variables: Any) -> bool:
    env = ansible_env(str(ROLE / "templates"))
    conditions = condition if isinstance(condition, list) else [condition]
    return all(env.compile_expression(str(c))(**variables) for c in conditions)


def test_check_mode_skips_the_shaper_until_its_unit_is_written() -> None:
    """`--check` writes no unit file, and the systemd module fails on a unit not on disk."""
    task = _first(lambda task: _systemd(task).get("name") == UNIT and "state" in _systemd(task))
    when = TASKS[task]["when"]
    present = {"stat": {"exists": True}}
    new, same = {"changed": True}, {"changed": False}
    assert not _holds(when, ansible_check_mode=True, gateway_uplink_sysfs=present, gateway_shaper_unit=new)
    assert _holds(when, ansible_check_mode=True, gateway_uplink_sysfs=present, gateway_shaper_unit=same)
    assert _holds(when, ansible_check_mode=False, gateway_uplink_sysfs=present, gateway_shaper_unit=new)


def test_the_playbook_maps_the_profiles_rates() -> None:
    plays = yaml.safe_load(
        (REPO / "infra" / "ansible" / "playbooks" / "provision-rpi4.yml").read_text(encoding="utf-8")
    )
    for play in plays:
        for role in play.get("roles", []):
            if isinstance(role, dict) and role.get("role", "").endswith("/gateway"):
                variables = role["vars"]
                for direction in ("down", "up"):
                    expected = f"{{{{ config.networking.edge.uplink.bandwidth.{direction}_kbit }}}}"
                    assert variables[f"gateway_uplink_{direction}_kbit"] == expected
                return
    raise AssertionError("provision-rpi4.yml runs no gateway role")
