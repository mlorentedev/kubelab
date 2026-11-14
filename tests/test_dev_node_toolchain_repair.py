"""The dev node repairs a pinned node that lost its npm (#3477).

`mise ls --missing` answers whether a version directory exists, not whether the
toolchain in it works. On ace2 an interrupted `npm update --global` (2026-10-31)
left `node/24.19.0/bin/` without `npm`, `npx`, `corepack` and `yarn`: npm had
moved them aside under temporary names and never put them back. The directory
was still there, so the role skipped the install, and the next task called an
`npm` that did not exist. Every untagged provision failed at that task.

The role now checks the entry point the next task uses and reinstalls the pinned
node when it is gone. Static: reads the role only.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE_TASKS = REPO / "infra/ansible/roles/dev_node/tasks/main.yml"
BIN = "{{ dev_node_home }}/.local/share/mise/installs/node/{{ dev_node_toolchains.node }}/bin/{{ item }}"


def _tasks() -> list[dict]:
    flat: list[dict] = []
    for task in yaml.safe_load(ROLE_TASKS.read_text(encoding="utf-8")):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _index(predicate) -> int:
    for i, task in enumerate(_tasks()):
        if predicate(task):
            return i
    raise AssertionError("task not found")


def _module(task: dict, name: str) -> dict:
    body = task.get(name)
    return body if isinstance(body, dict) else {}


def _stat_index() -> int:
    return _index(lambda t: _module(t, "ansible.builtin.stat").get("path") == BIN)


def _repair_index() -> int:
    return _index(lambda t: "mise install --force node@" in str(_module(t, "ansible.builtin.command").get("cmd", "")))


def _npm_install_index() -> int:
    return _index(lambda t: t.get("loop") == "{{ dev_node_global_agent_npm_packages }}")


def test_the_role_checks_the_node_entry_points_it_runs() -> None:
    stat = _tasks()[_stat_index()]
    assert stat.get("loop") == ["npm", "npx"], "npm runs the next task; npx is wrapped into /usr/local/bin"
    assert stat.get("register") == "_mise_node_bins"
    assert stat.get("check_mode") is False, "a dry run must still see a broken toolchain"


def test_a_missing_npm_forces_a_reinstall_of_the_pinned_node() -> None:
    repair = _tasks()[_repair_index()]
    assert repair["ansible.builtin.command"]["cmd"] == (
        "{{ dev_node_home }}/.local/bin/mise install --force node@{{ dev_node_toolchains.node }}"
    ), "reinstall the pinned version only; a bare `--force` would rebuild every toolchain"
    assert repair.get("when") == "_mise_node_bins.results | rejectattr('stat.exists') | list | length > 0"


def test_the_repair_runs_before_anything_uses_npm() -> None:
    assert _stat_index() < _repair_index() < _npm_install_index()
