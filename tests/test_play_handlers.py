"""A later failure in a play behind the lab edge does not drop the handlers it notified (#2824).

A play's roles share one handler phase: Ansible runs the handlers notified in
`roles:` and `tasks:` once both have finished, and a task that fails the play drops
every handler still pending. Behind the edge a play fails on purpose when a sized
pull outlasts its budget (#2742), after base_system, ssh_hardening and node_notify
have notified theirs. The rerun finds their files already written and fires none.

`force_handlers: true` keeps them: they run at the end of the play, where they would
have run had it passed. The edge's own play is the exception. The gateway role runs
its handlers inside the role, in the order the uplink needs, and a play-level
`force_handlers` would also run the uplink's netplan handlers after a failure. So
no role after the edge's last flush may notify at all.
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


def test_no_shared_task_file_notifies_or_flushes():
    """Roles and plays import these, and the resolution reads only `roles/<role>/tasks`
    and a play's own tasks, which sees everything only while these notify nothing."""
    for path in sorted((ROLES.parent / "playbooks/_includes").glob("*.yml")):
        tasks = list(_task_list(yaml.safe_load(path.read_text(encoding="utf-8"))))
        assert not any("notify" in task or task.get("meta") == "flush_handlers" for task in tasks), path.name


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


def _flushes(role: str) -> bool:
    files = (ROLES / role / "tasks").glob("**/*.yml")
    tasks = (task for path in files for task in _task_list(yaml.safe_load(path.read_text(encoding="utf-8"))))
    return any(task.get("meta") == "flush_handlers" for task in tasks)


def test_the_edges_play_runs_its_handlers_inside_its_roles_instead():
    [play] = [play for _, play in _plays() if "gateway" in _roles(play)]
    assert play.get("force_handlers") is not True
    roles = [Path(entry["role"] if isinstance(entry, dict) else entry).name for entry in play["roles"]]
    flushing = [i for i, role in enumerate(roles) if _flushes(role)]
    assert flushing, "no role in the edge's play flushes its handlers"
    last = flushing[-1]
    assert roles.index("gateway") <= last, "gateway flushes what the roles before it notified"
    unflushed = [role for role in roles[last + 1 :] if _role_notifies(role)]
    assert not unflushed, (
        f"{unflushed} notify after the edge's last flush ({roles[last]}), and the edge's play cannot "
        "force handlers. Act in the task on a `register`ed change instead; or flush inside the role "
        "if only the edge runs it (a flush in a fleet role fires netplan and tailscaled handlers "
        "mid-play on nodes reached over the tailnet); or split the play after the gateway role."
    )
