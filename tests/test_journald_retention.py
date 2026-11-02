"""A node with a large disk does not inherit the SD-card journal cap (#2702)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ANSIBLE = Path(__file__).resolve().parent.parent / "infra/ansible"
DEFAULTS = yaml.safe_load((ANSIBLE / "roles/base_system/defaults/main.yml").read_text(encoding="utf-8"))
LARGE_DISK = ("ace1", "ace2", "bee")
SMALL_DISK = ("rpi3", "rpi4", "gcp1")
# The VPS is decided in `provision.yml`, tested below. aws1 is retired.
DECIDED_ELSEWHERE = ("vps", "aws1")


def _base_system_play(node: str) -> dict:
    plays = yaml.safe_load((ANSIBLE / f"playbooks/provision-{node}.yml").read_text(encoding="utf-8"))
    (play, *_) = [p for p in plays if "base_system" in str(p.get("roles", "")) + str(p.get("tasks", ""))]
    return play


def test_the_default_stays_the_small_disk_bound() -> None:
    assert DEFAULTS["journald_system_max_use"] == "20M"
    assert DEFAULTS["journald_large_disk_max_use"] == "1G"


@pytest.mark.parametrize("node", LARGE_DISK)
def test_a_large_disk_node_declares_the_larger_cap(node: str) -> None:
    assert _base_system_play(node)["vars"]["journald_system_max_use"] == "{{ journald_large_disk_max_use }}"


def test_the_vps_takes_the_larger_cap_through_the_generic_play() -> None:
    (play,) = yaml.safe_load((ANSIBLE / "playbooks/provision.yml").read_text(encoding="utf-8"))
    (task,) = [t for t in play["pre_tasks"] if "journald_system_max_use" in t.get("set_fact", {})]
    assert task["set_fact"]["journald_system_max_use"] == "{{ journald_large_disk_max_use }}"
    assert task["when"] == "'vps' in group_names"


@pytest.mark.parametrize("node", SMALL_DISK)
def test_a_small_disk_node_keeps_the_bound(node: str) -> None:
    assert "journald_system_max_use" not in _base_system_play(node).get("vars", {})


def test_every_node_that_runs_base_system_is_classified() -> None:
    """A new node has to pick a side, or it would stay on 20M with nothing going red."""
    running = {
        path.stem.removeprefix("provision-")
        for path in (ANSIBLE / "playbooks").glob("provision-*.yml")
        if "base_system" in path.read_text(encoding="utf-8")
    }
    assert running == {*LARGE_DISK, *SMALL_DISK, *DECIDED_ELSEWHERE}
