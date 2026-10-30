"""A later failure in a play behind the lab edge does not drop the handlers it notified (#2824).

A play's roles share one handler phase: Ansible runs the handlers notified in
`roles:` and `tasks:` once both have finished, and a task that fails the play drops
every handler still pending. Behind the edge a play fails on purpose when a sized
pull outlasts its budget (#2742), after base_system, ssh_hardening and node_notify
have notified theirs. The rerun finds their files already written and fires none.

`force_handlers: true` keeps them: they run at the end of the play, where they would
have run had it passed. The edge's own play is the exception. The gateway role runs
its handlers inside the role, in the order the uplink needs, and a play-level
`force_handlers` would also run the uplink's netplan handlers after a failure.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.test_image_pull_budget import _behind_the_edge, _networking, _nodes, _plays, _roles, _task_list

ROLES = Path(__file__).resolve().parents[1] / "infra/ansible/roles"


def _notifies(tasks: list | None) -> bool:
    return any("notify" in task for task in _task_list(tasks))


def _role_notifies(role: str) -> bool:
    files = (ROLES / role / "tasks").glob("**/*.yml")
    return any(_notifies(yaml.safe_load(path.read_text(encoding="utf-8"))) for path in files)


def _plays_behind_the_edge_that_notify() -> dict[str, dict]:
    networking = _networking()
    found = {}
    for name, play in _plays():
        if not any(_behind_the_edge(node, networking) for node in _nodes(play["hosts"], networking)):
            continue
        tasks = (play.get(key) for key in ("pre_tasks", "tasks", "post_tasks"))
        if any(_role_notifies(role) for role in _roles(play)) or any(_notifies(t) for t in tasks):
            found[f"{name}: {play.get('name', play['hosts'])}"] = play
    return found


def test_the_resolution_finds_the_plays_the_ticket_names():
    names = {key.split(":")[0] for key in _plays_behind_the_edge_that_notify()}
    assert {"provision-ace1.yml", "provision-ace2.yml", "provision-bee.yml", "provision-rpi3.yml"} <= names
    assert "provision-rpi4.yml" in names, "the edge's play notifies too; it is excluded by name, not by accident"


def test_a_play_behind_the_edge_keeps_its_handlers_through_a_later_failure():
    unforced = [
        key
        for key, play in _plays_behind_the_edge_that_notify().items()
        if "gateway" not in _roles(play) and play.get("force_handlers") is not True
    ]
    assert not unforced, f"set `force_handlers: true` on: {unforced}"


def test_the_edges_play_runs_its_handlers_inside_the_gateway_role_instead():
    gateway = [play for _, play in _plays() if "gateway" in _roles(play)]
    assert gateway, "the edge's play is gone, or no longer reads as applying the gateway role"
    assert all(play.get("force_handlers") is not True for play in gateway)
    tasks = yaml.safe_load((ROLES / "gateway/tasks/main.yml").read_text(encoding="utf-8"))
    assert any(task.get("meta") == "flush_handlers" for task in _task_list(tasks))
