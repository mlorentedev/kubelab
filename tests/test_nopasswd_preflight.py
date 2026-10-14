"""#1229: the NOPASSWD pre-flight runs `sudo -n true` as the SSH user.

Run with `become: true`, Ansible escalates first, with the `-K` password when one
is given, so the inner `sudo -n` already runs as root and passes whether or not
NOPASSWD is configured. The check could not fail. Every `sudo -n true` task must
therefore resolve to `become: false`, from the task or from its play.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PLAYBOOKS = Path(__file__).resolve().parents[1] / "infra/ansible/playbooks"


def _sudo_checks() -> list:
    found = []
    for path in sorted(PLAYBOOKS.glob("*.yml")):
        for play in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
            for task in play.get("tasks", []) or []:
                command = task.get("command") or task.get("raw") or task.get("ansible.builtin.command")
                if isinstance(command, str) and command.strip() == "sudo -n true":
                    become = task.get("become", play.get("become", False))
                    found.append(pytest.param(become, id=f"{path.name}:{task.get('name')}"))
    return found


def test_the_fleet_has_nopasswd_checks() -> None:
    """A floor, so the parametrised test cannot pass by finding nothing."""
    assert len(_sudo_checks()) >= 8


@pytest.mark.parametrize("become", _sudo_checks())
def test_the_nopasswd_check_runs_without_escalation(become: bool) -> None:
    assert become is False, "with become, the check passes whether or not NOPASSWD is set"
