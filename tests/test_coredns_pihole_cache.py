"""A Corefile change must reach clients when the deploy says it did (lesson-560).

Clients ask Pi-hole, and Pi-hole caches each answer CoreDNS gave it for the
record's TTL. The CoreDNS `hosts` plugin answers with a TTL of 3600s, so after a
deploy that moved `status.kubelab.live`, CoreDNS answered the new address and
Pi-hole kept serving the old one, with 710s still to run, measured 2026-10-11.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TASKS = Path(__file__).resolve().parent.parent / "infra/ansible/roles/coredns/tasks/main.yml"


def _tasks() -> list[dict]:
    play = yaml.safe_load(TASKS.read_text())
    return [task for block in play for task in block.get("block", [block])]


def _task(name: str) -> dict:
    found = [t for t in _tasks() if t.get("name") == name]
    assert len(found) == 1, f"expected one task named {name!r}"
    return found[0]


def test_a_corefile_change_restarts_pihole() -> None:
    when = _task("Restart Pi-hole on config change")["when"]
    assert "corefile.changed" in when and "pihole_conf.changed" in when, when


def test_the_corefile_task_is_the_one_registered_as_corefile() -> None:
    assert _task("Template Corefile")["register"] == "corefile"


def test_pihole_restarts_after_coredns() -> None:
    names = [t.get("name") for t in _tasks()]
    assert names.index("Restart CoreDNS on config change") < names.index("Restart Pi-hole on config change")
