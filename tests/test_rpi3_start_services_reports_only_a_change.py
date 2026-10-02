"""rpi3's `docker compose up -d` reports `changed` only when compose did something.

It carried `changed_when: true`, so every provision of rpi3 ended `changed=1` and
the second run could never show `changed=0` (measured 2026-10-02). Same rule as
`beelink_services`: a container Started or Created (Recreated included) is a
change, `Running` is not.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TASKS = Path(__file__).resolve().parent.parent / "infra/ansible/roles/rpi3_services/tasks/main.yml"


def test_start_services_derives_changed_from_compose_output() -> None:
    (task,) = [t for t in yaml.safe_load(TASKS.read_text()) if t.get("name") == "Start services"]
    changed_when = task.get("changed_when")
    assert changed_when is not True, "changed_when: true makes every run report a change"
    assert task.get("register"), "the condition needs compose's output"
    for word in ("Started", "Created"):
        assert word in str(changed_when), word


def test_only_a_container_outside_the_stack_is_force_removed() -> None:
    """The legacy cleanup removed `uptime-kuma` on every run, compose's own included.

    It carried `changed_when: false`, so each provision took the external monitor of
    prod down and recreated it while reporting nothing (measured 2026-10-02: the
    container was 2 minutes old after a run that reported only `Start services`).
    Same guard as `roles/glances`: remove it only when it exists and is not labelled
    with this stack's compose project.
    """
    tasks = yaml.safe_load(TASKS.read_text())
    removals = [t for t in tasks if "docker rm -f uptime-kuma" in str(t.get("command", ""))]
    assert removals, "the legacy cleanup is gone; delete this test with it"
    for task in removals:
        when = " ".join(task.get("when") or []) if isinstance(task.get("when"), list) else str(task.get("when", ""))
        assert "rc == 0" in when, f"'{task['name']}' runs even when no container exists"
        assert "rpi3_deploy_dir | basename" in when, f"'{task['name']}' removes the stack's own container"
        assert task.get("changed_when") is not False, f"'{task['name']}' hides the removal it makes"
