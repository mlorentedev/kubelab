"""#1229: the NOPASSWD pre-flight runs `sudo -n true` as the SSH user.

Run with `become: true`, Ansible escalates first, with the `-K` password when one
is given, so the inner `sudo -n` already runs as root and passes whether or not
NOPASSWD is configured. The check could not fail. Every `sudo -n true` task must
therefore resolve to `become: false`, from the task or from its play.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

PLAYBOOKS = Path(__file__).resolve().parents[1] / "infra/ansible/playbooks"
SUDO_N = re.compile(r"\bsudo\s+-n\b")
TASK_LISTS = ("pre_tasks", "tasks", "post_tasks", "handlers")
BLOCK_LISTS = ("block", "rescue", "always")
MODULES = ("command", "ansible.builtin.command", "shell", "ansible.builtin.shell", "raw", "ansible.builtin.raw")


def _command(task: dict[str, Any]) -> str:
    """The command a task runs, in the free-form or the `cmd:` spelling; "" for any other module."""
    for module in MODULES:
        value = task.get(module)
        if isinstance(value, dict):
            value = value.get("cmd") or value.get("_raw_params")
        if isinstance(value, str):
            return value
    return ""


def _walk(tasks: list[dict[str, Any]] | None, become: bool, where: str) -> list:
    """Each `sudo -n` task under `tasks`, with the `become` it resolves to, blocks included."""
    found = []
    for task in tasks or []:
        resolved = task.get("become", become)
        for key in BLOCK_LISTS:
            found += _walk(task.get(key), resolved, where)
        if SUDO_N.search(_command(task)):
            found.append(pytest.param(resolved, id=f"{where}:{task.get('name')}"))
    return found


def _sudo_checks() -> list:
    found = []
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        for play in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            for key in TASK_LISTS:
                found += _walk(play.get(key), play.get("become", False), path.name)
    return found


def test_every_sudo_check_in_the_playbooks_is_seen() -> None:
    """The collector finds each `sudo -n` the files hold, so a respelled task cannot slip past it."""
    written = sum(
        len(SUDO_N.findall(line))
        for path in PLAYBOOKS.glob("*.yml")
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.lstrip().startswith("#")
    )
    assert written >= 8, "the fleet lost its NOPASSWD pre-flights"
    assert len(_sudo_checks()) == written


@pytest.mark.parametrize("become", _sudo_checks())
def test_the_nopasswd_check_runs_without_escalation(become: bool) -> None:
    assert become is False, "with become, the check passes whether or not NOPASSWD is set"
