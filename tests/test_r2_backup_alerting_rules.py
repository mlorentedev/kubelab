"""Tests for R2 Backup in-cluster watcher and Grafana alerting rules (OBS-015)."""

from __future__ import annotations

from pathlib import Path
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICES_DIR = REPO_ROOT / "infra" / "k8s" / "base" / "services"


def test_r2_backup_rules_syntax_and_structure() -> None:
    rules_file = SERVICES_DIR / "grafana-alerting" / "r2-backup-rules.yaml"
    assert rules_file.exists(), "r2-backup-rules.yaml must exist"

    data = yaml.safe_load(rules_file.read_text())
    assert data["apiVersion"] == 1
    assert "groups" in data
    assert len(data["groups"]) > 0

    group = data["groups"][0]
    assert group["name"] == "backup"
    assert len(group["rules"]) > 0

    rule = group["rules"][0]
    assert rule["uid"] == "obs015-r2-backup-health"
    assert rule["noDataState"] == "Alerting", "Loss of watcher logs must alert immediately"
    assert rule["execErrState"] == "Alerting"


def test_r2_backup_watcher_manifest() -> None:
    watcher_file = SERVICES_DIR / "r2-backup-watcher.yaml"
    assert watcher_file.exists(), "r2-backup-watcher.yaml must exist"

    docs = list(yaml.safe_load_all(watcher_file.read_text()))
    kinds = [d["kind"] for d in docs if d and "kind" in d]
    assert "ServiceAccount" in kinds
    assert "CronJob" in kinds

    cronjob = next(d for d in docs if d.get("kind") == "CronJob")
    assert cronjob["metadata"]["name"] == "r2-backup-watcher"

    # Shape only. This used to pin the literal "0 6 * * *", which recorded the
    # value without the reason and so had nothing to say when that value turned
    # out to be wrong -- it would have gone red on the fix and green on the
    # defect. What actually constrains this schedule is its relationship to the
    # rule's lookback window, and that is asserted in
    # test_the_emitter_runs_often_enough_to_keep_its_own_dead_man_quiet.
    fields = cronjob["spec"]["schedule"].split()
    assert len(fields) == 5, f"not a 5-field cron expression: {cronjob['spec']['schedule']!r}"


def test_kustomization_includes_r2_backup_watcher_and_rules() -> None:
    kustomization_file = REPO_ROOT / "infra" / "k8s" / "base" / "kustomization.yaml"
    content = kustomization_file.read_text()
    assert "services/r2-backup-watcher.yaml" in content
    assert "services/grafana-alerting/r2-backup-rules.yaml" in content


def _emitter_period_hours() -> float:
    """How often the watcher CronJob actually produces a log line, in hours."""
    import re

    docs = list(yaml.safe_load_all((SERVICES_DIR / "r2-backup-watcher.yaml").read_text()))
    cron = next(d for d in docs if d and d.get("kind") == "CronJob")
    schedule = cron["spec"]["schedule"]

    hour_field = schedule.split()[1]
    if step := re.fullmatch(r"\*/(\d+)", hour_field):
        return float(step.group(1))
    if hour_field == "*":
        return 1.0
    # A fixed list of hours: the period is the largest gap between runs, since
    # that is the one the alert window has to survive.
    hours = sorted(int(h) for h in hour_field.split(","))
    if len(hours) == 1:
        return 24.0
    gaps = [b - a for a, b in zip(hours, hours[1:])] + [hours[0] + 24 - hours[-1]]
    return float(max(gaps))


def _rule_lookback_hours() -> float:
    """The window the alert's Loki query looks back over, in hours."""
    import re

    data = yaml.safe_load((SERVICES_DIR / "grafana-alerting" / "r2-backup-rules.yaml").read_text())
    rule = data["groups"][0]["rules"][0]
    expr = next(d["model"]["expr"] for d in rule["data"] if d.get("datasourceUid") == "loki")

    match = re.search(r"\[(\d+)([hmd])\]", expr)
    assert match, f"no range selector in the rule's Loki query: {expr!r}"
    value, unit = int(match.group(1)), match.group(2)
    return value * {"m": 1 / 60, "h": 1.0, "d": 24.0}[unit]


def test_the_emitter_runs_often_enough_to_keep_its_own_dead_man_quiet() -> None:
    """With noDataState: Alerting, the producer's period IS the alert's margin.

    A daily emitter against a 24h lookback has exactly none: the moment one run
    is late or skipped, the window empties and the rule pages about backups
    that are fine.

    Measured 2026-08-23, both environments in one morning. Prod: rule deployed
    04:40Z with no history in Loki, fired 04:59Z, cleared 06:19Z on the daily
    06:00 tick. Staging: same rule at 07:06Z, past that day's only tick, with
    no way to clear until 06:00 the next morning -- a ~23h alert announcing
    that nodes may be unprotected, in an environment where nothing was wrong.

    Three samples inside the window is the bar: it survives one missed run
    without firing, and still catches an emitter that has genuinely stopped.
    """
    period = _emitter_period_hours()
    lookback = _rule_lookback_hours()
    samples = lookback / period

    assert samples >= 3, (
        f"the watcher runs every {period:g}h against a {lookback:g}h lookback, so the window "
        f"holds {samples:g} sample(s). One late run empties it and the dead-man fires on a "
        f"healthy fleet -- and a fresh environment inherits the alert until the first tick."
    )
