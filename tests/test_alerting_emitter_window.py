"""Every `noDataState: Alerting` rule's emitter must keep its own window fed (#1320).

With `noDataState: Alerting`, the producer's period IS the rule's margin: a
window that holds one sample empties the moment one run is late, and the rule
pages about a healthy fleet. #1318 measured that on the R2 rule (a daily
emitter against a 24h window) and fixed it with a guard that read one rule.
The property is fleet-wide, and the case nobody checks by hand is a rule added
later with a slow emitter, so this guard enumerates instead of naming.

The floor is 2 samples: one missed run is survivable, two consecutive are not.
That is the measured minimum across the rules that existed when the guard was
written (2026-11-02); raising it to 3, the R2 guard's bar, turns the disk,
quota and edge rules red and is the operator's call (OBS-042).

A rule under the floor, or one with no emitter this guard can resolve, needs an
entry in `EXEMPT` with the reason its own definition gives.
"""

from __future__ import annotations

import re

import pytest
import yaml

from tests.test_alerting_unwrap_grouping import ALERTING_DIR, CRONJOB_CONTAINERS, REPO_ROOT

SERVICES_DIR = REPO_ROOT / "infra/k8s/base/services"

#: The fewest emitter runs an alert window may hold.
MIN_SAMPLES = 2

#: uid -> why the rule may sit under the floor or has no resolvable emitter.
EXEMPT = {
    "obs015-deadmansswitch-heartbeat": (
        "no CronJob emitter: it is Grafana's own heartbeat, outside this property by shape (#1320)"
    ),
    "backup032-on-demand-freshness": (
        "a 7h window over a 6h watcher on purpose: two consecutive probes must agree before an "
        "on-demand node reads as stale, and watcher silence pages through obs015-r2-backup-health"
    ),
    "backup032-r2-backup-shrink": (
        "a 9h window compares consecutive 6h probes; watcher silence pages through obs015-r2-backup-health"
    ),
}

_UNIT_MINUTES = {"s": 1 / 60, "m": 1.0, "h": 60.0, "d": 1440.0}


def _alerting_rules() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(ALERTING_DIR.glob("*rules.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for group in doc.get("groups") or []:
            for rule in group.get("rules") or []:
                if rule.get("noDataState") == "Alerting":
                    found.append((path.name, rule))
    return found


def _loki_exprs(rule: dict) -> str:
    return "\n".join(
        str((item.get("model") or {}).get("expr", ""))
        for item in rule.get("data") or []
        if item.get("datasourceUid") != "__expr__"
    )


def _emitter(rule: dict) -> str | None:
    containers = {c for c in CRONJOB_CONTAINERS if f'container="{c}"' in _loki_exprs(rule)}
    return containers.pop() if len(containers) == 1 else None


def _period_minutes(schedule: str) -> float:
    """The longest gap between two runs of a 5-field cron schedule, in minutes."""
    minute, hour, *rest = schedule.split()
    assert len(rest) == 3 and all(f == "*" for f in rest), f"unsupported schedule {schedule!r}"
    if step := re.fullmatch(r"\*/(\d+)", minute):
        assert hour == "*", f"unsupported schedule {schedule!r}"
        return float(step.group(1))
    assert minute.isdigit(), f"unsupported schedule {schedule!r}"
    if hour == "*":
        return 60.0
    if step := re.fullmatch(r"\*/(\d+)", hour):
        return float(step.group(1)) * 60
    hours = sorted(int(h) for h in hour.split(","))
    gaps = [b - a for a, b in zip(hours, hours[1:], strict=False)] + [hours[0] + 24 - hours[-1]]
    return float(max(gaps)) * 60


def _schedule(container: str) -> str:
    docs = yaml.safe_load_all((SERVICES_DIR / f"{container}.yaml").read_text(encoding="utf-8"))
    cronjob = next(d for d in docs if d and d.get("kind") == "CronJob")
    return cronjob["spec"]["schedule"]


def _window_minutes(rule: dict) -> float:
    """The shortest range selector in the rule's queries: the window that empties first."""
    windows = [int(v) * _UNIT_MINUTES[u] for v, u in re.findall(r"\[(\d+)([smhd])\]", _loki_exprs(rule))]
    assert windows, f"{rule['uid']}: no range selector in its query"
    return min(windows)


def _samples(rule: dict) -> float | None:
    container = _emitter(rule)
    if container is None:
        return None
    return _window_minutes(rule) / _period_minutes(_schedule(container))


def test_the_scan_finds_the_rules_it_claims_to_guard() -> None:
    """Anti-vacuity: an assertion over an empty list guards nothing (lesson 416)."""
    uids = {r["uid"] for _, r in _alerting_rules()}
    assert len(uids) >= 10, uids
    assert {"obs042-disk-watcher-silent", "obs015-r2-backup-health", "obs010-quota-requests"} <= uids
    # Finding the rules is not measuring them: an emptied CRONJOB_CONTAINERS would
    # resolve no emitter and leave every check below with nothing to compare.
    measured = [r["uid"] for _, r in _alerting_rules() if r["uid"] not in EXEMPT and _samples(r) is not None]
    assert len(measured) >= 9, measured  # 9 when written (2026-11-02)


def test_the_cron_parser_reads_every_shape_in_use() -> None:
    assert _period_minutes("*/15 * * * *") == 15
    assert _period_minutes("0 */6 * * *") == 360
    assert _period_minutes("0 * * * *") == 60
    assert _period_minutes("0 6 * * *") == 1440
    assert _period_minutes("0 6,18 * * *") == 720


@pytest.mark.parametrize(("filename", "rule"), _alerting_rules(), ids=lambda v: v["uid"] if isinstance(v, dict) else v)
def test_the_emitter_keeps_its_own_dead_man_quiet(filename: str, rule: dict) -> None:
    uid = rule["uid"]
    if uid in EXEMPT:
        return
    samples = _samples(rule)
    assert samples is not None, (
        f"{uid} ({filename}) alerts on no data, but no single CronJob emitter could be resolved "
        "from its query, so nothing checks that its window stays fed. Read a container in "
        "CRONJOB_CONTAINERS, or add it to EXEMPT with the reason its definition gives."
    )
    assert samples >= MIN_SAMPLES, (
        f"{uid} ({filename}): its window holds {samples:g} run(s) of {_emitter(rule)}. One late run "
        "empties it and the rule pages about a healthy fleet; a fresh environment inherits the "
        "alert until the first tick (#1318)."
    )


@pytest.mark.parametrize("uid", sorted(EXEMPT))
def test_every_exemption_is_still_needed(uid: str) -> None:
    """An exemption that matches no rule, or a rule now above the floor, is stale."""
    rule = next((r for _, r in _alerting_rules() if r["uid"] == uid), None)
    assert rule is not None, f"EXEMPT names {uid}, which is not a noDataState: Alerting rule"
    samples = _samples(rule)
    assert samples is None or samples < MIN_SAMPLES, (
        f"{uid} now holds {samples:g} samples, at or above the floor: drop its exemption"
    )
