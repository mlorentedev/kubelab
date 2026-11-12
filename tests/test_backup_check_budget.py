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


# BACKUP-081 (#3084): nothing watched the pack count, so the first sign that 1/t no
# longer fit was the check timing out again. The watcher reports each node's packs,
# and a rule fires before one check's share outgrows its budget. Its threshold is
# t x what one check can read, computed here from the role's own values, so the
# rule and `node_backup_check_read_data_groups` cannot drift apart.
#
# Measured on rpi4, the slowest node and the largest repository, 2026-11-04 on the
# hotel uplink (defaults comment, #2920): a ~100s ship, a 107s plain check, and 1/8
# of ~800 packs (~100) read in 383s, 3.8 s/pack. A later run read 50 packs in 57s;
# the slow figure is the one a budget has to survive. Re-measure after the
# 2026-11-18 site move.
SHIP_SECONDS = 100
PLAIN_CHECK_SECONDS = 107
SECONDS_PER_PACK = 3.8
MARGIN = 0.8
RULES = REPO / "infra/k8s/base/services/grafana-alerting/r2-backup-rules.yaml"
CHECK_BUDGET_UID = "backup081-check-budget"


def _packs_per_check() -> int:
    return int(MARGIN * (_ship_timeout() - SHIP_SECONDS - PLAIN_CHECK_SECONDS) / SECONDS_PER_PACK)


def _check_budget_rule() -> dict:
    groups = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]
    rules = [r for g in groups for r in g["rules"] if r["uid"] == CHECK_BUDGET_UID]
    assert len(rules) == 1, f"no single rule {CHECK_BUDGET_UID}"
    return rules[0]


def test_the_check_budget_rule_fires_at_t_times_what_one_check_can_read():
    rule = _check_budget_rule()
    threshold = next(d for d in rule["data"] if d["refId"] == rule["condition"])
    (condition,) = threshold["model"]["conditions"]
    t = int(DEFAULTS["node_backup_check_read_data_groups"])
    assert condition["evaluator"] == {"type": "gt", "params": [t * _packs_per_check()]}, (
        f"the threshold must be t ({t}) x {_packs_per_check()} packs per check; "
        "change it with node_backup_check_read_data_groups, never alone"
    )


def test_the_check_budget_rule_reads_each_nodes_packs():
    expr = next(d for d in _check_budget_rule()["data"] if d["refId"] == "A")["model"]["expr"]
    assert "metric=`r2_backup_node`" in expr and "unwrap packs" in expr
    # lesson-512: a plain `| json` lets Vector's `node` label fold every backup node into one series.
    assert 'backup_node="node"' in expr and "by (backup_node)" in expr


def test_the_check_budget_alert_reaches_the_log_tier_in_both_environments():
    """A warning to act on within weeks, not an interruption: never the page tier."""
    from tests.test_forge_review_failed_route import _policy, _receivers

    title = _check_budget_rule()["title"]
    for env in ("staging", "prod"):
        assert _receivers(_policy(env), {"alertname": title}) == ["apprise-log"], env
