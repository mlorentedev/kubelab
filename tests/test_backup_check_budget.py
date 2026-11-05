"""BACKUP-078 (#2920): the weekly integrity check has to finish to say anything.

The check instance shares the ship unit's 600s budget on purpose: `restic
check` holds the repository's exclusive lock, and ship and prune only wait for
a lock about that long. So the check is kept inside the budget by reading a
subset of packs (`node_backup_check_read_data_groups`), and the on-demand nodes
that catch up after a boot are spread over a window wider than that budget
times their number, so they do not all read from R2 over one uplink at once.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
ROLE = REPO / "infra/ansible/roles/node_backup"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))

_UNITS = {"s": 1, "sec": 1, "min": 60, "m": 60, "h": 3600, "hr": 3600}


def _seconds(value: str) -> int:
    match = re.fullmatch(r"(\d+)\s*([a-z]*)", str(value).strip())
    assert match, f"unparsed systemd time span: {value!r}"
    return int(match.group(1)) * _UNITS[match.group(2) or "s"]


def _ship_timeout() -> int:
    unit = (ROLE / "templates/node-backup-ship.service.j2").read_text(encoding="utf-8")
    match = re.search(r"^TimeoutStartSec=(\d+)$", unit, re.MULTILINE)
    assert match, "the ship unit declares no literal TimeoutStartSec"
    return int(match.group(1))


def _on_demand_backup_nodes() -> list[str]:
    nodes = COMMON["networking"]["nodes"]
    return sorted(n for n in COMMON["backup"]["sources"] if nodes.get(n, {}).get("location") == "on-demand")


def test_the_check_timer_uses_its_own_spread():
    timer = (ROLE / "templates/node-backup-ship-check.timer.j2").read_text(encoding="utf-8")
    assert "RandomizedDelaySec={{ node_backup_check_randomized_delay }}" in timer


def test_catch_up_checks_are_spread_wider_than_their_budgets_end_to_end():
    on_demand = _on_demand_backup_nodes()
    assert on_demand, "no on-demand backup node found: the test would pass vacuously"
    spread = _seconds(DEFAULTS["node_backup_check_randomized_delay"])
    assert spread >= _ship_timeout() * len(on_demand), (
        f"{len(on_demand)} on-demand nodes ({', '.join(on_demand)}) catch up at boot within {spread}s, "
        f"less than their {_ship_timeout()}s budgets laid end to end"
    )


def test_the_check_reads_a_subset_of_packs():
    # 1 meant a full read every week: right at 6-17 packs (2026-09-30), timed out
    # at 364-961 (2026-11-01). Measured 2026-11-04, see the defaults comment.
    assert int(DEFAULTS["node_backup_check_read_data_groups"]) >= 16
