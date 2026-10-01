"""rpi3's dry run survives a stack unit that does not exist yet (#1983).

Under `--check` the template that installs `kubelab-rpi3.service` only predicts
the file, so a `systemd` task enabling it finds no unit and fails. Measured
2026-10-01: `make provision NODE=rpi3 ENV=prod CHECK=1` died there, because
rpi3 had never received the unit #1278 added.
"""

from __future__ import annotations

from pathlib import Path

import yaml

TASKS = Path(__file__).resolve().parent.parent / "infra/ansible/roles/rpi3_services/tasks/main.yml"


def _task(name: str) -> dict:
    for task in yaml.safe_load(TASKS.read_text()):
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r}")


def test_the_unit_file_is_read_before_the_template() -> None:
    names = [task.get("name") for task in yaml.safe_load(TASKS.read_text())]
    probe = names.index("Check whether the Compose stack unit is already installed")
    assert probe < names.index("Install the Compose stack systemd unit")
    assert _task(names[probe]).get("register") == "_rpi3_unit_file"


def test_the_enable_skips_only_a_unit_missing_from_disk() -> None:
    when = _task("Enable the Compose stack unit at boot").get("when")
    # Both halves matter: `not ansible_check_mode` alone would also skip the
    # enable on a dry run where the unit exists, hiding a disabled unit. And the
    # template's `changed` is the wrong signal: it is also true when an existing
    # unit is only updated, which would hide a disabled unit just the same.
    assert when == "not (ansible_check_mode and not _rpi3_unit_file.stat.exists)", when
