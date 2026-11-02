"""The rpi_boot role, run task by task against a simulated host.

The role's decisions are Jinja over three files it reads (the cgroup controllers,
the cmdline on the boot partition, the running kernel's `/proc/cmdline`), so a test
that read the YAML would see expression text. This walks `tasks/main.yml` in order
the way Ansible does: block conditions are inherited, a `set_fact` renders natively,
a `slurp` reads the simulated file, and a `copy` writes it. A module the role starts
using that is not modelled here fails the test instead of being skipped.
"""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import pytest
import yaml
from jinja2 import StrictUndefined, UndefinedError
from jinja2.nativetypes import NativeEnvironment

from tests.ansible_jinja import _to_bool

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra" / "ansible" / "roles" / "rpi_boot"
PLAYBOOKS = REPO / "infra" / "ansible" / "playbooks"

CMDLINE = "/boot/firmware/cmdline.txt"
CONTROLLERS = "/sys/fs/cgroup/cgroup.controllers"
PROC = "/proc/cmdline"
WITH_MEMORY = "cpuset cpu io memory pids"
WITHOUT_MEMORY = "cpuset cpu io pids"
BASE = "console=serial0,115200 console=tty1 root=LABEL=writable rootfstype=ext4 rootwait"
REGDOM = "cfg80211.ieee80211_regdom"


class RoleFailed(Exception):
    pass


def _env() -> NativeEnvironment:
    env = NativeEnvironment(undefined=StrictUndefined, keep_trailing_newline=True)
    env.filters["bool"] = _to_bool
    env.filters["b64decode"] = lambda value: base64.b64decode(value).decode()
    env.filters["regex_escape"] = re.escape
    env.tests["match"] = lambda value, pattern: re.match(pattern, value) is not None
    return env


ENV = _env()


def _render(value: Any, facts: dict[str, Any]) -> Any:
    if isinstance(value, str) and "{{" in value:
        return ENV.from_string(value).render(facts)
    if isinstance(value, list):
        return [_render(item, facts) for item in value]
    if isinstance(value, dict):
        return {key: _render(item, facts) for key, item in value.items()}
    return value


def _true(condition: Any, facts: dict[str, Any]) -> bool:
    conditions = condition if isinstance(condition, list) else [condition]
    return all(c if isinstance(c, bool) else _to_bool(_render("{{ " + str(c) + " }}", facts)) for c in conditions)


def _flat(tasks: list[dict[str, Any]], inherited: list[Any]) -> list[tuple[dict[str, Any], list[Any]]]:
    out: list[tuple[dict[str, Any], list[Any]]] = []
    for task in tasks:
        own = inherited + ([task["when"]] if "when" in task else [])
        if "block" in task:
            out.extend(_flat(task["block"], own))
        else:
            out.append((task, own))
    return out


def _module(task: dict[str, Any]) -> tuple[str, Any]:
    skip = {"name", "when", "register", "failed_when", "loop", "changed_when", "tags"}
    (name,) = [key for key in task if key not in skip]
    return name.removeprefix("ansible.builtin."), task[name]


class Host:
    def __init__(self, files: dict[str, str], after_reboot: dict[str, str] | None = None) -> None:
        self.files = dict(files)
        self.after_reboot = after_reboot
        self.written: dict[str, str] = {}
        self.backups: list[str] = []
        self.read: list[str] = []
        self.messages: list[str] = []
        self.rebooted = False

    def run(self, **role_vars: Any) -> Host:
        defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
        facts: dict[str, Any] = {
            **defaults,
            **role_vars,
            "ansible_facts": {"date_time": {"iso8601_basic_short": "20261025T120000"}},
        }
        tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
        for task, conditions in _flat(tasks, []):
            if all(_true(c, facts) for c in conditions):
                self._step(task, facts)
        return self

    def _step(self, task: dict[str, Any], facts: dict[str, Any]) -> None:
        module, args = _module(task)
        tolerant = task.get("failed_when") is False
        if module == "assert":
            if not _true(args["that"], facts):
                raise RoleFailed(args.get("fail_msg", "assert failed"))
            return
        if module == "set_fact":
            for key, value in args.items():
                try:
                    facts[key] = _render(value, facts)
                except UndefinedError:
                    if not tolerant:
                        raise
            return
        if "loop" in task:
            items = _render(task["loop"], facts)
            result: Any = {"results": [self._call(module, _render(args, {**facts, "item": i}), i) for i in items]}
        else:
            result = self._call(module, _render(args, facts), None, tolerant)
        if "register" in task:
            facts[task["register"]] = result

    def _call(self, module: str, args: Any, item: Any, tolerant: bool = False) -> dict[str, Any]:
        if module == "slurp":
            self.read.append(args["src"])
            if args["src"] not in self.files:
                if tolerant:
                    return {"failed": True}
                raise RoleFailed(f"no such file {args['src']}")
            return {"content": base64.b64encode(self.files[args["src"]].encode()).decode()}
        if module == "stat":
            return {"item": item, "stat": {"exists": args["path"] in self.files, "path": args["path"]}}
        if module == "copy":
            if args.get("remote_src"):
                self.backups.append(args["dest"])
            else:
                self.written[args["dest"]] = args["content"]
                self.files[args["dest"]] = args["content"]
            return {"changed": True}
        if module == "file":
            return {"changed": False}
        if module == "debug":
            self.messages.append(str(args.get("msg", "")))
            return {}
        if module == "fail":
            raise RoleFailed(args["msg"])
        if module == "reboot":
            self.rebooted = True
            self.files[PROC] = self.files[CMDLINE].splitlines()[0]
            self.files.update(self.after_reboot or {})
            return {"changed": True}
        raise NotImplementedError(f"module {module!r} is not modelled")


def _rpi4(cmdline: str, proc: str | None = None) -> Host:
    return Host({CONTROLLERS: WITH_MEMORY, CMDLINE: cmdline + "\n", PROC: proc if proc is not None else cmdline})


def test_no_parameter_is_removed_unless_a_play_declares_it() -> None:
    """Raspberry Pi OS stores the Wi-Fi country as this same token: raspi-config's
    `do_wifi_country` writes `cfg80211.ieee80211_regdom=` into cmdline.txt. rpi3 runs
    this role and its only network is Wi-Fi, so a default that removed the token
    could take a headless node off the air."""
    defaults = yaml.safe_load((ROLE / "defaults" / "main.yml").read_text(encoding="utf-8"))
    assert defaults["rpi_boot_absent_params"] == []


def test_a_node_with_the_controller_and_nothing_declared_reads_no_cmdline() -> None:
    host = _rpi4(f"{BASE} {REGDOM}=DE").run()
    assert host.read == [CONTROLLERS]
    assert not host.written and not host.backups and not host.rebooted


@pytest.mark.parametrize("value", ["DE", "US"])
def test_a_declared_parameter_is_removed_whatever_its_value(value: str) -> None:
    host = _rpi4(f"{BASE} {REGDOM}={value} quiet").run(rpi_boot_absent_params=[REGDOM])
    assert host.written == {CMDLINE: f"{BASE} quiet\n"}
    assert len(host.backups) == 1


def test_a_parameter_that_only_shares_the_prefix_is_kept() -> None:
    host = _rpi4(f"{BASE} {REGDOM}_extra=1 {REGDOM}=DE").run(rpi_boot_absent_params=[REGDOM])
    assert host.written == {CMDLINE: f"{BASE} {REGDOM}_extra=1\n"}


def test_a_node_with_the_controller_gains_no_cgroup_parameter() -> None:
    host = _rpi4(f"{BASE} {REGDOM}=DE").run(rpi_boot_absent_params=[REGDOM])
    assert "cgroup" not in host.written[CMDLINE]


def test_a_cmdline_without_the_parameter_is_left_alone() -> None:
    host = _rpi4(BASE).run(rpi_boot_absent_params=[REGDOM])
    assert not host.written and not host.backups and not host.rebooted
    assert not any("NOT YET ACTIVE" in m for m in host.messages)


def test_a_removal_the_kernel_has_not_booted_is_reported_pending() -> None:
    host = _rpi4(BASE, proc=f"{BASE} {REGDOM}=DE").run(rpi_boot_absent_params=[REGDOM])
    assert not host.written and not host.rebooted
    assert any("NOT YET ACTIVE" in m for m in host.messages)


def test_an_allowed_reboot_activates_the_removal() -> None:
    host = _rpi4(f"{BASE} {REGDOM}=DE").run(rpi_boot_absent_params=[REGDOM], rpi_boot_allow_reboot=True)
    assert host.rebooted
    assert REGDOM not in host.files[PROC]


def test_a_reboot_that_did_not_drop_the_parameter_fails() -> None:
    host = Host(
        {CONTROLLERS: WITH_MEMORY, CMDLINE: f"{BASE} {REGDOM}=DE\n", PROC: f"{BASE} {REGDOM}=DE"},
        after_reboot={PROC: f"{BASE} {REGDOM}=DE"},
    )
    with pytest.raises(RoleFailed):
        host.run(rpi_boot_absent_params=[REGDOM], rpi_boot_allow_reboot=True)


def test_a_missing_controller_still_gets_its_parameters() -> None:
    host = Host({CONTROLLERS: WITHOUT_MEMORY, CMDLINE: BASE + "\n", PROC: BASE}).run()
    assert host.written == {CMDLINE: f"{BASE} cgroup_enable=memory cgroup_memory=1\n"}


def test_one_write_adds_and_removes() -> None:
    host = Host({CONTROLLERS: WITHOUT_MEMORY, CMDLINE: f"{BASE} {REGDOM}=DE\n", PROC: BASE})
    host.run(rpi_boot_absent_params=[REGDOM])
    assert host.written == {CMDLINE: f"{BASE} cgroup_enable=memory cgroup_memory=1\n"}


def _refusal() -> dict[str, Any]:
    tasks = yaml.safe_load((ROLE / "tasks" / "main.yml").read_text(encoding="utf-8"))
    flat = [task for task, _ in _flat(tasks, [])]
    return next(t for t in flat if t["name"] == "Refuse to write a command line that would not boot")


@pytest.mark.parametrize(
    ("line", "missing"),
    [
        ("console=tty1 rootwait", []),
        (f"{BASE}\nquiet", []),
        (BASE, ["cgroup_enable=memory"]),
        (f"{BASE} {REGDOM}=DE", []),
    ],
    ids=["no-root", "two-lines", "lost-a-required-parameter", "still-carries-a-removed-parameter"],
)
def test_the_refusal_catches_each_unbootable_or_unfinished_line(line: str, missing: list[str]) -> None:
    that = _refusal()["ansible.builtin.assert"]["that"]
    facts = {
        "_rpi_boot_cmdline_new": line,
        "_rpi_boot_missing_params": missing,
        "_rpi_boot_absent_pattern": f"^({re.escape(REGDOM)})(=|$)",
    }
    assert not _true(that, facts)
    assert _true(that, {**facts, "_rpi_boot_cmdline_new": f"{BASE} quiet", "_rpi_boot_missing_params": []})


def _plays() -> dict[str, list[Any]]:
    out = {}
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        plays = yaml.safe_load(path.read_text(encoding="utf-8")) or []
        out[path.name] = [r for p in plays if isinstance(p, dict) for r in p.get("roles") or []]
    return out


def _role_name(entry: Any) -> str:
    return Path(entry["role"] if isinstance(entry, dict) else entry).name


def _role_vars(entry: Any) -> dict[str, Any]:
    """A role entry's variables, under `vars:` or inline."""
    if not isinstance(entry, dict):
        return {}
    inline = {k: v for k, v in entry.items() if k not in ("role", "tags", "vars", "when")}
    return {**inline, **(entry.get("vars") or {})}


def test_the_edge_play_removes_the_regdomain_before_the_gateway_reads_it() -> None:
    """The regulatory domain is the site's, set through modprobe.d by the gateway role,
    and a cmdline value would override it (#2668)."""
    roles = _plays()["provision-rpi4.yml"]
    names = [_role_name(r) for r in roles]
    boot = roles[names.index("rpi_boot")]
    assert _role_vars(boot)["rpi_boot_absent_params"] == [REGDOM]
    assert "boot" in boot["tags"]
    assert names.index("rpi_boot") < names.index("gateway")


def test_no_other_play_removes_a_parameter() -> None:
    for name, roles in _plays().items():
        if name == "provision-rpi4.yml":
            continue
        for role in roles:
            assert "rpi_boot_absent_params" not in _role_vars(role), name
