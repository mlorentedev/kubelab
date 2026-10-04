"""`make backup-node INTEGRITY=1` runs the weekly integrity-check unit now (BACKUP-063).

The weekly check reads pack data back from R2, and its footprint on the RPi3
(`MemoryMax=128M`) is what decides how much it reads. Measuring it by hand, with
restic started over SSH, would measure a different process: no cgroup, no
timeout, no `OnFailure`. So the measurement starts the real unit, and these
tests pin that it does.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from jinja2 import Environment

REPO = Path(__file__).resolve().parent.parent
PLAYBOOK = REPO / "infra/ansible/playbooks/backup-node.yml"
DEFAULTS = REPO / "infra/ansible/roles/node_backup/defaults/main.yml"
MAKEFILE = REPO / "Makefile"


def _play() -> dict:
    [play] = yaml.safe_load(PLAYBOOK.read_text())
    return play


def _unit(**extra_vars: object) -> str:
    play = _play()
    assert play["vars_files"] == ["../roles/node_backup/defaults/main.yml"], "unit names must come from the role"
    context = {**yaml.safe_load(DEFAULTS.read_text()), **extra_vars}
    env = Environment()
    # Ansible's `bool` filter, which plain Jinja lacks: "true"/"yes"/"1" are true.
    env.filters["bool"] = lambda v: str(v).strip().lower() in {"true", "yes", "1", "on"}
    return env.from_string(play["vars"]["backup_unit"]).render(**context).strip()


def test_the_frequent_ship_unit_is_the_default() -> None:
    assert _unit() == yaml.safe_load(DEFAULTS.read_text())["node_backup_ship_service_name"]


def test_integrity_selects_the_weekly_check_unit() -> None:
    assert _unit(integrity="true") == yaml.safe_load(DEFAULTS.read_text())["node_backup_ship_check_service_name"]


def test_every_task_acts_on_the_selected_unit() -> None:
    """A task that named the ship unit literally would report the wrong unit's result."""
    text = PLAYBOOK.read_text()
    assert "node-backup-ship.service" not in text
    assert "node-backup-ship-check.service" not in text


def test_the_make_flag_reaches_the_playbook() -> None:
    recipe = re.search(r"^backup-node:.*?(?=^\S|\Z)", MAKEFILE.read_text(), re.S | re.M)
    assert recipe, "Makefile has no backup-node target"
    assert '$(if $(INTEGRITY),--extra-vars "integrity=true",)' in recipe.group(0)
    assert re.search(r"infra ansible run -p backup-node .*\$\(_INTEGRITY\)", recipe.group(0))


def test_prune_selects_the_retention_unit() -> None:
    """`make backup-node PRUNE=1` runs node-backup-prune.service now (BACKUP-057 Q6)."""
    assert _unit(prune="true") == yaml.safe_load(DEFAULTS.read_text())["node_backup_prune_service_name"]


def test_only_prune_1_prunes() -> None:
    import subprocess

    for value, expected in (("", False), ("0", False), ("1", True)):
        out = subprocess.run(
            ["make", "-n", "-C", str(REPO), "backup-node", "NODE=beelink", "ENV=prod", f"PRUNE={value}"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert ("prune=true" in out) is expected, (value, out)


def test_the_deploy_can_be_limited_to_one_node() -> None:
    """`make backup NODE=<node>` rolls a role change out to one node first."""
    import subprocess

    def expand(*args: str) -> str:
        return subprocess.run(
            ["make", "-n", "-C", str(REPO), "backup", "ENV=prod", *args], capture_output=True, text=True, check=True
        ).stdout

    assert "-l beelink" in expand("NODE=beelink")
    assert " -l " not in expand()
