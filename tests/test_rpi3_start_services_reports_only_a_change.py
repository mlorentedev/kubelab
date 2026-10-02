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
