"""The VPS no longer carries certbot or nginx, and the play that says so runs (OPS-047, #2701).

Two retired designs left their TLS stack on the VPS: the 2025 nginx + certbot
setup for mlorente.dev, and the 2026-02-26 Headscale TCP-passthrough setup, in
which Headscale terminated TLS itself from a certbot certificate. Traefik
replaced the first and K3s Traefik the second, so nothing reads what certbot
produces; every certificate it issued has expired, and `certbot.service` has
failed every 12 hours since.

Ansible is additive: deleting a role never undoes what it installed, so the
removal is a set of explicit tasks, and a task that exists proves nothing. What
makes the unit stop failing is that the packages are purged, the directory that
holds the Cloudflare credential is gone, and the failed state that survives the
unit file is cleared, all as root, on the host the VPS play targets. These
tests read the tasks as the play applies them rather than the list in
isolation, because a list nothing runs removes nothing.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import jinja2
import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ANSIBLE = REPO / "infra/ansible"
ROLE = ANSIBLE / "roles/headscale"
VPS_PLAYBOOK = ANSIBLE / "playbooks/deploy-vps.yml"

# What the issue names, plus nginx-common: on Ubuntu 24.04 it no longer depends on
# nginx, so purging nginx alone leaves it installed with /etc/nginx (measured in a
# booted 24.04 container). The list in the role may grow; it may not lose one.
REQUIRED_PACKAGES = {
    "certbot",
    "python3-certbot",
    "python3-certbot-dns-cloudflare",
    "python3-certbot-nginx",
    "nginx",
    "nginx-common",
}
LETSENCRYPT_DIR = "/etc/letsencrypt"

# What `systemctl list-units --failed --plain --no-legend --no-pager 'certbot*'` prints on
# a host that purged certbot and has not reset its units (measured on a booted 24.04 container).
FAILED_CERTBOT_UNITS = (
    "certbot.service not-found failed failed certbot.service\ncertbot.timer   not-found failed failed certbot.timer"
)

APT_MODULES = ("apt", "ansible.builtin.apt")
FILE_MODULES = ("file", "ansible.builtin.file")
COMMAND_MODULES = ("command", "ansible.builtin.command")

_BARE_VAR = re.compile(r"^\{\{\s*([A-Za-z_][A-Za-z0-9_]*)\s*\}\}$")


def _defaults() -> dict[str, Any]:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _tasks() -> list[dict]:
    return yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8"))


def _module(task: dict, names: tuple[str, ...]) -> dict | None:
    for name in names:
        if name in task:
            return task[name] or {}
    return None


def _resolve(value: Any) -> Any:
    """A `{{ var }}` the task takes from the role defaults, resolved; anything else as written.

    Only a bare reference resolves. A task that builds its target out of an
    expression is not something this file can read, and failing on it is the
    point: the removal must stay legible to the test that guards it.
    """
    if isinstance(value, str):
        match = _BARE_VAR.match(value)
        if match:
            defaults = _defaults()
            assert match.group(1) in defaults, f"{match.group(1)} is not declared in the role defaults"
            return defaults[match.group(1)]
    return value


def _vps_play() -> dict:
    plays = yaml.safe_load(VPS_PLAYBOOK.read_text(encoding="utf-8"))
    assert len(plays) == 1, "deploy-vps.yml is expected to be one play"
    return plays[0]


def _privileged(task: dict) -> bool:
    """Whether the task runs as root: its own `become`, else the play's."""
    return bool(task.get("become", _vps_play().get("become", False)))


def _removal_packages() -> tuple[dict, set[str]]:
    """The task that purges packages, and the packages it names."""
    found = []
    for task in _tasks():
        apt = _module(task, APT_MODULES)
        if apt is not None and apt.get("state") == "absent":
            names = _resolve(apt.get("name"))
            found.append((task, {names} if isinstance(names, str) else set(names or [])))
    assert found, "the headscale role has no task that removes packages"
    task, names = found[0]
    return task, names


def _letsencrypt_removal() -> dict:
    for task in _tasks():
        file = _module(task, FILE_MODULES)
        if file is None or file.get("state") != "absent":
            continue
        paths = _resolve(file.get("path"))
        if LETSENCRYPT_DIR in ([paths] if isinstance(paths, str) else (paths or [])):
            return task
        # A loop over paths: the items are the targets.
        if LETSENCRYPT_DIR in [_resolve(item) for item in (_resolve(task.get("loop")) or [])]:
            return task
    raise AssertionError(f"the headscale role does not remove {LETSENCRYPT_DIR}")


def _failed_unit_read() -> dict:
    """The task that lists the failed certbot units the reset is gated on."""
    found = [
        t
        for t in _tasks()
        if "systemctl list-units" in str(_module(t, COMMAND_MODULES)) and "certbot" in str(_module(t, COMMAND_MODULES))
    ]
    assert found, "no task reads which certbot units are failed"
    return found[0]


def _failed_unit_reset() -> dict:
    found = [
        t
        for t in _tasks()
        if "systemctl reset-failed" in str(_module(t, COMMAND_MODULES))
        and "certbot" in str(_module(t, COMMAND_MODULES))
    ]
    assert found, "no task clears the failed state of the removed certbot units"
    return found[0]


def _index(task: dict) -> int:
    """Position of a task in the role, by name (each call re-reads the file)."""
    return [candidate.get("name") for candidate in _tasks()].index(task["name"])


class TestTheVpsPlayRunsTheTeardown:
    """The role is only a removal if the play that targets the VPS applies it."""

    def test_the_vps_play_applies_the_headscale_role_unconditionally(self) -> None:
        play = _vps_play()
        assert play["hosts"] == "vps", "the teardown is meant for the VPS group"
        entries = [
            r for r in play["roles"] if isinstance(r, dict) and str(r.get("role", "")).endswith("roles/headscale")
        ]
        assert len(entries) == 1, "deploy-vps.yml must apply the headscale role exactly once"
        # Prod runs this play with k3s_servers set. The roles skipped there carry a
        # `when` on exactly that group; this one must not, or prod never loses certbot.
        assert "when" not in entries[0], "the headscale role must run in prod: no `when` may gate it"


class TestPackagesArePurged:
    def test_every_retired_package_is_removed(self) -> None:
        _, names = _removal_packages()
        missing = REQUIRED_PACKAGES - names
        assert not missing, f"the teardown no longer removes: {sorted(missing)}"

    def test_removal_purges_so_no_conffile_is_left_behind(self) -> None:
        # Without purge a removed package stays in dpkg's `rc` state with its
        # config (the nginx site files, certbot's cron.d entry) still on disk.
        task, _ = _removal_packages()
        assert _module(task, APT_MODULES).get("purge") is True

    def test_removal_is_unconditional(self) -> None:
        task, _ = _removal_packages()
        assert "when" not in task, "a gated removal reaches only the hosts its condition names"

    def test_removal_runs_as_root(self) -> None:
        # deploy-vps.yml has no play-level become; apt as the SSH user fails.
        task, _ = _removal_packages()
        assert _privileged(task)


class TestLetsEncryptDirectoryIsRemoved:
    def test_directory_is_removed_unconditionally(self) -> None:
        task = _letsencrypt_removal()
        assert "when" not in task

    def test_removal_runs_as_root(self) -> None:
        # The directory is root-owned (it holds cloudflare.ini, mode 0600).
        assert _privileged(_letsencrypt_removal())

    def test_directory_goes_after_the_packages(self) -> None:
        # certbot's own purge scripts look in it; removing it first only
        # leaves the package's postrm with less to do, but the order is the
        # one a reader expects and costs nothing to hold.
        assert _index(_removal_packages()[0]) < _index(_letsencrypt_removal())


class TestFailedUnitIsCleared:
    """A purged unit stays in `systemctl --failed` as `not-found failed` until reset.

    Measured on a booted Ubuntu 24.04 container: after `apt-get purge` alone,
    `certbot.service` and `certbot.timer` both still list as `not-found failed`.
    Purging certbot therefore does not satisfy "the VPS no longer lists
    certbot.service as failed" by itself.
    """

    def test_reset_runs_after_the_packages_are_removed(self) -> None:
        assert _index(_removal_packages()[0]) < _index(_failed_unit_reset())

    def test_reset_runs_as_root(self) -> None:
        assert _privileged(_failed_unit_reset())

    def test_the_read_precedes_the_reset(self) -> None:
        assert _index(_failed_unit_read()) < _index(_failed_unit_reset())

    def test_the_read_never_reports_a_change(self) -> None:
        # A read changes nothing. Left reporting `changed`, every run would end at
        # changed=1 and the second run could never be changed=0.
        assert _failed_unit_read().get("changed_when") is False

    def test_the_read_runs_under_check_mode(self) -> None:
        # Ansible skips a command in check mode, and a skipped task registers no
        # `stdout`: the reset's condition would then raise on `make deploy CHECK=1`.
        assert _failed_unit_read().get("check_mode") is False

    def test_the_read_asks_for_failed_units_only(self) -> None:
        # Without `--failed` it lists every loaded certbot unit, so the reset would
        # fire on a host where certbot is still installed and healthy.
        assert "--failed" in str(_module(_failed_unit_read(), COMMAND_MODULES))

    @pytest.mark.parametrize(
        ("stdout", "resets"),
        [("", False), (FAILED_CERTBOT_UNITS, True)],
        ids=["nothing-failed", "units-failed"],
    )
    def test_the_reset_runs_exactly_when_the_read_found_a_failed_unit(self, stdout: str, resets: bool) -> None:
        """The second run reads nothing and so resets nothing: that is what makes it changed=0.

        `reset-failed` exits 0 whether or not anything matches, so left unconditional it
        would report `changed` on every run. The condition is evaluated, not read: a
        `when` that merely mentions certbot, or that ignores the read's output, passes
        a reading of its text and fails here. `rc` is 0 in both cases because
        `systemctl list-units` exits 0 with or without a match.
        """
        read, reset = _failed_unit_read(), _failed_unit_reset()
        conditions = reset.get("when")
        assert conditions is not None, "an unconditional reset reports changed on every run"
        result = {"rc": 0, "stdout": stdout, "stdout_lines": stdout.splitlines(), "stderr": "", "changed": False}
        env = ansible_env(str(ROLE / "templates"))
        try:
            applies = all(
                env.compile_expression(str(c))(**{read["register"]: result})
                for c in (conditions if isinstance(conditions, list) else [conditions])
            )
        except jinja2.UndefinedError:
            pytest.fail("the reset's condition does not read the registered result of the read task")
        assert bool(applies) is resets


class TestTheTeardownDoesNotGateTheRest:
    """`make deploy TARGET=vps ENV=prod` is also how an ACL change reaches the VPS.

    The target passes no `--tags`, so there is no ACL-only run to exempt: every
    deploy executes the whole role. A locked or broken dpkg fails the apt purge, and
    a purge that runs first would then stop the play before the policy is rendered,
    reloaded and probed. Running it last means the ACL work is done, or reverted by
    its own probe, before apt is touched, and the failure still fails the play.
    """

    @staticmethod
    def _tags(task: dict) -> list[str]:
        tags = task.get("tags") or []
        return [tags] if isinstance(tags, str) else list(tags)

    def _cleanup_positions(self) -> list[int]:
        return [i for i, task in enumerate(_tasks()) if "cleanup" in self._tags(task)]

    def test_every_teardown_task_is_tagged_cleanup(self) -> None:
        tasks = _tasks()
        names = [
            _removal_packages()[0]["name"],
            _letsencrypt_removal()["name"],
            _failed_unit_read()["name"],
            _failed_unit_reset()["name"],
        ]
        untagged = [t["name"] for t in tasks if t["name"] in names and "cleanup" not in self._tags(t)]
        assert not untagged, f"outside the ordering guard below, because untagged: {untagged}"

    def test_the_teardown_is_the_last_thing_the_role_does(self) -> None:
        positions = self._cleanup_positions()
        total = len(_tasks())
        assert len(positions) >= 4, "the teardown tasks are no longer tagged `cleanup`"
        assert positions == list(range(total - len(positions), total)), (
            "a task tagged `cleanup` sits before Headscale's own tasks: a failed purge would stop the play "
            "before the ACL policy is applied. Put new Headscale tasks above the teardown."
        )

    def test_the_acl_policy_and_its_probe_come_first(self) -> None:
        """Without this the test above passes on a role that has lost its ACL tasks."""
        tasks = _tasks()
        first_cleanup = self._cleanup_positions()[0]
        policy = [
            i
            for i, t in enumerate(tasks)
            if "policy.hujson.j2" in str(_module(t, ("template", "ansible.builtin.template")))
        ]
        probe = [i for i, t in enumerate(tasks) if "block" in t and "rescue" in t]
        assert policy and probe, "the role no longer renders the ACL policy or probes it"
        assert max(policy + probe) < first_cleanup

    def test_a_teardown_command_cannot_report_changed_on_every_run(self) -> None:
        for task in (_tasks()[i] for i in self._cleanup_positions()):
            if _module(task, COMMAND_MODULES) is not None:
                assert task.get("changed_when") is False or "when" in task, (
                    f"{task['name']!r} runs a command that would report changed on every run"
                )


class TestNothingReinstallsWhatTheTeardownRemoves:
    """A package one role installs and another purges flaps on every provision."""

    def _installers(self) -> list[tuple[str, set[str]]]:
        found: list[tuple[str, set[str]]] = []
        for path in sorted(ANSIBLE.rglob("*.yml")):
            if "generated" in path.parts or "inventories" in path.parts:
                continue
            try:
                doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            except yaml.YAMLError:
                continue
            found.extend(_apt_installs(doc, path.relative_to(REPO).as_posix(), _role_defaults(path)))
        return found

    def test_the_scan_sees_installs(self) -> None:
        """A scan that matches nothing passes on any tree."""
        assert len(self._installers()) >= 5, "the matcher finds no apt installs; it is broken"

    def test_the_scan_reads_through_a_role_default_list(self) -> None:
        """`base_system` installs from `{{ base_packages }}`; a scan of literals alone misses a list there."""
        names = {name for where, names in self._installers() for name in names if "roles/base_system/" in where}
        assert "curl" in names, "the scan does not resolve a package list declared in role defaults"

    def test_no_role_or_playbook_installs_a_retired_package(self) -> None:
        clashes = [
            f"{where}: {sorted(names & REQUIRED_PACKAGES)}"
            for where, names in self._installers()
            if names & REQUIRED_PACKAGES
        ]
        assert not clashes, "installed by one task and purged by the headscale teardown:\n  " + "\n  ".join(clashes)


def _role_defaults(path: Path) -> dict[str, Any]:
    """The defaults of the role a task file belongs to; empty for a playbook."""
    parts = path.relative_to(ANSIBLE).parts
    if parts[0] != "roles":
        return {}
    defaults = ANSIBLE / "roles" / parts[1] / "defaults/main.yml"
    return (yaml.safe_load(defaults.read_text(encoding="utf-8")) or {}) if defaults.exists() else {}


def _package_names(name: Any, defaults: dict[str, Any]) -> set[str]:
    """Package names an apt `name:` can carry: literals, plus any role-default list its expression mentions."""
    if isinstance(name, list):
        return {n for item in name for n in _package_names(item, defaults)}
    if not isinstance(name, str):
        return set()
    names = {name}
    for ident in re.findall(r"[A-Za-z_]\w*", name):
        value = defaults.get(ident)
        if isinstance(value, list):
            names |= {item for item in value if isinstance(item, str)}
    return names


def _apt_installs(node: Any, where: str, defaults: dict[str, Any]) -> list[tuple[str, set[str]]]:
    """Every apt task that installs (any state but `absent`), at any depth."""
    found: list[tuple[str, set[str]]] = []
    if isinstance(node, list):
        for item in node:
            found.extend(_apt_installs(item, where, defaults))
    elif isinstance(node, dict):
        apt = _module(node, APT_MODULES)
        if isinstance(apt, dict) and apt.get("state") != "absent" and "name" in apt:
            found.append((where, _package_names(apt["name"], defaults)))
        for value in node.values():
            if isinstance(value, (list, dict)):
                found.extend(_apt_installs(value, where, defaults))
    return found
