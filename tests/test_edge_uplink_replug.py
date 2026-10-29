"""The uplink comes back when its adapter re-enumerates (#2766).

netplan starts the uplink's supplicant once, with systemd-networkd at boot, and
nothing starts it when the adapter appears later: after a replug or a USB reset the
edge stays off the internet until a reboot. A udev rule wants the supplicant and
the shaper each time the adapter appears, and the supplicant is bound to the
adapter, so it stops when the adapter leaves and the next appearance starts it.

Nothing is installed into the device's `.wants/`: systemd follows a static link
there whenever a start job for the device is enqueued, present or not, so with the
adapter missing the shaper failed with result `dependency` every 90 s and paged an
outage the liveness check already owns. `SYSTEMD_WANTS=` is acted on only when the
device first becomes active (systemd.device(5)), and a renamed adapter becomes active
on the move event after its add, so the rule must not match on add alone.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2.exceptions import UndefinedError

from tests.ansible_jinja import ansible_env, task_runs

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "gateway"
TASKS: list[dict[str, Any]] = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text())
INTERFACE = yaml.safe_load((REPO / "infra" / "config" / "values" / "common.yaml").read_text())["networking"]["edge"][
    "uplink"
]["interface"]
DEVICE = f"sys-subsystem-net-devices-{INTERFACE}.device"
SHAPER = "kubelab-edge-shaper.service"
SUPPLICANT = f"netplan-wpa-{INTERFACE}.service"
RULES_DIR = "/etc/udev/rules.d/"
DROP_IN_DIR = f"/etc/systemd/system/{SUPPLICANT}.d"
WANTS_LINK = f"/etc/systemd/system/{DEVICE}.wants/{SHAPER}"
KINDS = ("wifi_open", "wifi_psk", "ethernet")


def _vars(kind: str) -> dict[str, Any]:
    return {"ansible_managed": "managed", "gateway_uplink_interface": INTERFACE, "gateway_uplink_kind": kind}


def _render(source: str, kind: str) -> str:
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True, lstrip_blocks=True)
    return env.get_template(source).render(**_vars(kind))


def _expand(value: object) -> str:
    """The path as the edge sees it; a looped task's `{{ item }}` path stays as written."""
    try:
        return ansible_env(".").from_string(str(value)).render(gateway_uplink_interface=INTERFACE)
    except UndefinedError:
        return str(value)


def _dest(task: dict[str, Any]) -> str:
    return _expand((task.get("template") or task.get("ansible.builtin.template") or {}).get("dest", ""))


def _path(task: dict[str, Any]) -> str:
    return _expand((task.get("file") or task.get("ansible.builtin.file") or {}).get("path", ""))


def _index(predicate: Any) -> int:
    return next(i for i, task in enumerate(TASKS) if predicate(task))


def _rule_task() -> int:
    return _index(lambda task: _dest(task).startswith(RULES_DIR))


def _rule(kind: str) -> str:
    source = (TASKS[_rule_task()].get("template") or {})["src"]
    return _render(source, kind)


def _wanted(kind: str) -> list[str]:
    lines = [line for line in _rule(kind).splitlines() if line and not line.startswith("#")]
    assert len(lines) == 1, lines
    match = re.search(r'ENV\{SYSTEMD_WANTS\}\+="([^"]+)"', lines[0])
    assert match, lines[0]
    return match.group(1).split()


# ------------------------------------------------------------------ the rule


def test_the_rule_sorts_after_the_rule_that_names_the_adapter() -> None:
    """`NAME==` matches only once 80-net-setup-link.rules has applied the .link file's
    name, and rules files run in lexical order across every rules directory."""
    name = Path(_dest(TASKS[_rule_task()])).name
    prefix = re.match(r"(\d+)-", name)
    assert prefix and int(prefix.group(1)) > 80, name
    assert name.endswith(".rules")


@pytest.mark.parametrize("kind", KINDS)
def test_the_rule_matches_the_named_adapter_when_it_appears(kind: str) -> None:
    """The name, not the MAC: the .link file pins the MAC, and no committed file carries it."""
    rule = next(line for line in _rule(kind).splitlines() if line and not line.startswith("#"))
    assert 'SUBSYSTEM=="net"' in rule
    assert f'NAME=="{INTERFACE}"' in rule
    assert "address" not in rule.lower()


@pytest.mark.parametrize("kind", KINDS)
def test_the_rule_wants_the_units_on_every_event_but_remove(kind: str) -> None:
    """The .link file renames the adapter during its add event, which udev flags
    `ID_RENAMING=1`, and systemd ignores a device being renamed. The device becomes
    active on the move event that follows, so that is the event whose `SYSTEMD_WANTS`
    counts. Observed on the edge (#2766): the add carried the property, the move did
    not, and neither unit was ever started."""
    rule = next(line for line in _rule(kind).splitlines() if line and not line.startswith("#"))
    actions = re.findall(r'ACTION(==|!=)"([^"]*)"', rule)
    assert actions == [("!=", "remove")], rule


@pytest.mark.parametrize("kind", ["wifi_open", "wifi_psk"])
def test_a_wifi_uplink_wants_its_supplicant_and_the_shaper(kind: str) -> None:
    assert _wanted(kind) == [SUPPLICANT, SHAPER]


def test_an_ethernet_uplink_wants_only_the_shaper() -> None:
    """netplan writes no supplicant for a wired uplink, and networkd follows its carrier."""
    assert _wanted("ethernet") == [SHAPER]


def test_the_rule_is_checked_by_udev_before_it_replaces_the_live_one() -> None:
    task = TASKS[_rule_task()]
    assert task["template"]["validate"] == "udevadm verify --resolve-names=never %s"
    assert task["template"]["mode"] == "0644"


@pytest.mark.parametrize("kind", KINDS)
def test_udev_accepts_the_rendered_rule(kind: str, tmp_path: Path) -> None:
    if shutil.which("udevadm") is None:
        pytest.skip("udevadm is not installed")
    probe = subprocess.run(["udevadm", "verify", "--help"], capture_output=True, check=False)
    if probe.returncode != 0:
        pytest.skip("udevadm has no verify verb (systemd < 254)")
    rules = tmp_path / "90-rendered.rules"
    rules.write_text(_rule(kind))
    proc = subprocess.run(
        ["udevadm", "verify", "--resolve-names=never", str(rules)], capture_output=True, text=True, check=False
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_changed_rule_reloads_udev_before_the_adapter_is_renamed() -> None:
    """The reload is a task, not a handler, for the reason the .link file's is."""
    rule = _rule_task()
    reload = _index(lambda task: task.get("command") == "udevadm control --reload")
    rename = _index(lambda task: "udevadm trigger" in str(task.get("command")))
    register = TASKS[rule]["register"]
    assert rule < reload < rename
    present = {"ansible_facts": {"interfaces": [INTERFACE]}, "gateway_uplink_interface": INTERFACE}
    same = {"changed": False}
    assert task_runs(TASKS[reload], {**present, "gateway_uplink_link": same, register: {"changed": True}})
    assert not task_runs(TASKS[reload], {**present, "gateway_uplink_link": same, register: same})


# ------------------------------------------------------------ the supplicant


def _drop_in_task() -> int:
    return _index(lambda task: _dest(task).startswith(DROP_IN_DIR + "/"))


def test_the_supplicant_is_bound_to_the_adapter() -> None:
    """`Requires=` from netplan does not stop it when the adapter leaves; `BindsTo=` does,
    so the adapter's next appearance starts it again."""
    source = TASKS[_drop_in_task()]["template"]["src"]
    text = _render(source, "wifi_psk")
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert lines == ["[Unit]", f"BindsTo={DEVICE}"]


@pytest.mark.parametrize("kind", KINDS)
def test_the_drop_in_exists_only_for_a_wifi_uplink(kind: str) -> None:
    """A site that changes to a wired uplink leaves no drop-in for a unit netplan no longer writes."""
    dest = _dest(TASKS[_drop_in_task()])
    wifi = kind != "ethernet"
    writes = [task for task in TASKS if _dest(task) == dest]
    removes = [task for task in TASKS if _path(task) == dest]
    assert len(writes) == 1 and len(removes) == 1
    variables = _vars(kind)
    assert task_runs(writes[0], variables) is wifi
    assert removes[0]["file"]["state"] == "absent"
    assert task_runs(removes[0], variables) is not wifi


def test_a_changed_drop_in_reloads_systemd() -> None:
    dest = _dest(TASKS[_drop_in_task()])
    for task in TASKS:
        if dest in (_dest(task), _path(task)):
            assert task["notify"] == "reload systemd", task["name"]


# ---------------------------------------------------- nothing on the .wants/


def test_no_unit_the_role_ships_is_installed_into_the_devices_wants() -> None:
    for template in (ROLE / "templates").glob("*.j2"):
        assert not re.search(r"^WantedBy=sys-subsystem-net-devices-", template.read_text(), re.MULTILINE), template


def test_the_role_removes_the_shapers_old_link_on_the_device() -> None:
    """Ansible does not undo what a role stops declaring: an edge provisioned before
    #2766 keeps the link, and with it the failures every 90 s, until a task removes it."""
    remove = _index(lambda task: _path(task) == WANTS_LINK)
    assert TASKS[remove]["file"]["state"] == "absent"
    assert TASKS[remove]["notify"] == "reload systemd"
    assert "when" not in TASKS[remove]


def test_no_task_enables_the_shaper() -> None:
    """Enabling it would write the link back from an [Install] section."""
    for task in TASKS:
        module = task.get("systemd") or task.get("ansible.builtin.systemd") or {}
        if module.get("name") == SHAPER:
            assert "enabled" not in module, task["name"]


# --------------------------------------------------- the device's start job


DEVICE_DROP_IN_DIR = f"/etc/systemd/system/{DEVICE}.d"
DEFAULTS: dict[str, Any] = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text())
# systemd's DefaultDeviceTimeoutSec, the bound a missing adapter held network.target for (#2794).
SYSTEMD_DEVICE_TIMEOUT = 90


def _device_drop_in_task() -> int:
    return _index(lambda task: _dest(task).startswith(DEVICE_DROP_IN_DIR + "/"))


@pytest.mark.parametrize("kind", KINDS)
def test_a_missing_adapter_holds_the_boot_for_the_roles_bound_not_systemds(kind: str) -> None:
    """netplan's supplicant requires the adapter and is ordered before network.target, so
    with the adapter missing the boot waited out the device's start job: 90 s, holding
    docker, the LAN's DNS and tailscaled (#2794). The device's own drop-in bounds that
    job, the way systemd-fstab-generator bounds a mount's device (`JobRunningTimeoutSec=`).
    An adapter that appears later is still served: the udev rule starts the supplicant."""
    task = TASKS[_device_drop_in_task()]
    bound = DEFAULTS["gateway_uplink_device_timeout_seconds"]
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True, lstrip_blocks=True)
    text = env.get_template(task["template"]["src"]).render(**_vars(kind), gateway_uplink_device_timeout_seconds=bound)
    lines = [line for line in text.splitlines() if line and not line.startswith("#")]
    assert lines == ["[Unit]", f"JobRunningTimeoutSec={bound}s"]
    assert 5 <= bound < SYSTEMD_DEVICE_TIMEOUT


@pytest.mark.parametrize("kind", KINDS)
def test_the_device_bound_is_written_for_every_uplink_kind(kind: str) -> None:
    """It describes the adapter, not the supplicant: no condition, so a change of kind
    leaves nothing to remove."""
    assert task_runs(TASKS[_device_drop_in_task()], _vars(kind))


def test_the_device_bound_lands_in_a_directory_the_role_creates_and_reloads_systemd() -> None:
    task = TASKS[_device_drop_in_task()]
    assert task["notify"] == "reload systemd"
    assert task["template"]["mode"] == "0644"
    directory = _index(lambda t: _path(t) == DEVICE_DROP_IN_DIR)
    assert TASKS[directory]["file"]["state"] == "directory"
    assert directory < _device_drop_in_task()
