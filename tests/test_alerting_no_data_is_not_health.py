"""A rule reading a CronJob-sourced stream must not treat silence as health.

`obs015-disk-root-saturation` carried `noDataState: OK` until 2026-09-05 while
its sibling `obs015-pvc-unbound-failure`, **reading the same Loki stream**,
carried `Alerting`. That asymmetry is worse than either choice made
consistently: if `disk-watcher` stops, one rule goes red and the other goes
green from one cause, so the node whose disk is no longer measured is precisely
the node that reads as fine.

It survived because nothing compared the two. Each rule is locally plausible —
`OK` looks like "don't page me for a gap" — and the defect only exists in the
relationship between them, which no reader of one file section sees.

Found while planning OPS-024, which intended to feed five more nodes into that
rule. The plan would have added them to a rule that reports health when nobody
is reporting, and the spec's own acceptance criteria would have passed.

`CRONJOB_CONTAINERS` is IMPORTED, never copied: a container added there for the
grouping guard must not need remembering here too (the derivation discipline of
lesson 415 — a class whose members are listed twice acquires two truths).

Scope: this asserts the static property. That `Alerting` genuinely fires on
no-data is not asserted here — it is *observed*, in #1377, where this same rule
family alerted on a stopped watcher for a day and a half.
"""

from __future__ import annotations

import pathlib
import re

import pytest
import yaml

from tests.test_alerting_unwrap_grouping import ALERTING_DIR, CRONJOB_CONTAINERS


def _rules_over_cronjob_streams() -> list[tuple[str, str, dict]]:
    """(file, uid, rule) for every rule whose query reads a CronJob container."""
    found: list[tuple[str, str, dict]] = []
    for path in sorted(ALERTING_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for group in doc.get("groups") or []:
            for rule in group.get("rules") or []:
                queries = "".join(str((item.get("model") or {}).get("expr", "")) for item in rule.get("data") or [])
                if any(f'container="{c}"' in queries for c in CRONJOB_CONTAINERS):
                    found.append((path.name, rule.get("uid", "?"), rule))
    return found


def test_the_scan_finds_the_rules_it_claims_to_guard() -> None:
    """Anti-vacuity floor. Every assertion below is over this list, and an
    assertion over an empty list passes while guarding nothing — the failure
    this repo has now measured four times (lesson 416, #1565)."""
    rules = _rules_over_cronjob_streams()
    uids = {uid for _, uid, _ in rules}

    assert len(rules) >= 2, f"expected at least the two obs015 rules, found {uids}"
    assert {"obs015-pvc-unbound-failure", "obs015-disk-root-saturation"} <= uids


def _queries(rule: dict) -> str:
    return "".join(str((item.get("model") or {}).get("expr", "")) for item in rule.get("data") or [])


def _containers(rule: dict) -> set[str]:
    return {c for c in CRONJOB_CONTAINERS if f'container="{c}"' in _queries(rule)}


def _is_liveness(rule: dict) -> bool:
    """A rule whose only question is "is the watcher still reporting".

    It alerts on no data and its query has no grouping, so its label set cannot
    vanish: silence of the stream is the only way it goes empty (#1668).
    """
    return rule.get("noDataState") == "Alerting" and not re.search(r"\bby\s*\(", _queries(rule))


def _metrics(rule: dict) -> set[str | None]:
    """The `metric` values the rule filters on; `None` when it reads every line."""
    return set(re.findall(r"metric=`([^`]+)`", _queries(rule))) or {None}


def _streams(rule: dict) -> set[tuple[str, str | None]]:
    """(container, metric) pairs. One watcher emits several metrics, and a liveness
    rule counting one of them says nothing about the others."""
    return {(c, m) for c in _containers(rule) for m in _metrics(rule)}


def _watched_streams() -> set[tuple[str, str | None]]:
    return {s for _, _, r in _rules_over_cronjob_streams() if _is_liveness(r) for s in _streams(r)}


def _unwatched(rule: dict) -> set[tuple[str, str | None]]:
    watched = _watched_streams()
    return {(c, m) for c, m in _streams(rule) if (c, m) not in watched and (c, None) not in watched}


def test_the_disk_watcher_has_a_liveness_rule() -> None:
    """Anti-vacuity for the exemption below: the split of #1668 rests on it."""
    assert ("disk-watcher", "disk_pvc_health") in _watched_streams()
    assert ("disk-watcher", "disk_root_usage") in _watched_streams()


def test_a_liveness_rule_on_one_metric_does_not_watch_another() -> None:
    """The hole this guard had: it keyed on the container, so the PVC metric's
    liveness rule exempted a root-usage rule whose own line could stop alone."""
    pvc_only = {"data": [{"model": {"expr": '{container="disk-watcher"} | json | metric=`disk_pvc_health`'}}]}
    root = {"data": [{"model": {"expr": '{container="disk-watcher"} | json | metric=`disk_root_usage`'}}]}
    assert _streams(pvc_only) == {("disk-watcher", "disk_pvc_health")}
    assert ("disk-watcher", "disk_root_usage") in _streams(root)
    assert ("disk-watcher", "disk_pvc_health") not in _streams(root)


@pytest.mark.parametrize(
    ("filename", "uid"),
    [(f, u) for f, u, _ in _rules_over_cronjob_streams()],
    ids=[f"{u}" for _, u, _ in _rules_over_cronjob_streams()],
)
def test_no_data_is_not_reported_as_health(filename: str, uid: str) -> None:
    """A watcher that stops must not read as a healthy fleet.

    `noDataState: OK` on a rule fed by a single watcher converts that watcher's
    death into a green dashboard. The rule can then never fail: it reports the
    watcher's opinion when there is one, and health when there is not.

    The one way out is a separate liveness rule for the same container (#1668):
    then silence still pages, from a rule that says so, and the per-object rule
    can let a vanished label set resolve instead of holding it FIRING.
    """
    rule = next(r for f, u, r in _rules_over_cronjob_streams() if f == filename and u == uid)
    if rule.get("noDataState") == "Alerting":
        return
    unwatched = _unwatched(rule)
    assert not unwatched, (
        f"{uid} ({filename}) has noDataState={rule.get('noDataState')!r} and reads {sorted(unwatched, key=str)} "
        "(container, metric), which no liveness rule watches. No-data there means the watcher "
        "stopped, not that the thing being watched is well. Add an ungrouped `noDataState: "
        "Alerting` rule counting that metric (see `obs042-disk-watcher-silent`), or keep this one "
        "at Alerting."
    )


@pytest.mark.parametrize(
    ("filename", "uid"),
    [(f, u) for f, u, r in _rules_over_cronjob_streams() if r.get("noDataState") == "Alerting" and not _is_liveness(r)],
    ids=[u for _, u, r in _rules_over_cronjob_streams() if r.get("noDataState") == "Alerting" and not _is_liveness(r)],
)
def test_the_summary_names_the_watcher_as_a_cause(filename: str, uid: str) -> None:
    """`noDataState: Alerting` on a per-object rule gives it two causes, and a
    summary naming only the interesting one sends the responder to the wrong system.

    Not hypothetical: #1377 ran for a day and a half because the summary said a
    storage backend was preventing provisioning while every PVC was Bound and
    the real fault was a query that could not parse its own input. Trading a
    silent failure for a misleading alert is not a fix.

    A liveness rule is exempt: silence is its single cause, and its summary says so.
    """
    rule = next(r for f, u, r in _rules_over_cronjob_streams() if f == filename and u == uid)
    summary = str((rule.get("annotations") or {}).get("summary", "")).lower()

    assert "watcher" in summary, (
        f"{uid} ({filename}) alerts on no-data but its summary never names the watcher. "
        "The responder needs the cheap check in the alert text, not in a runbook they "
        "open after chasing the other cause."
    )

    # Naming the watcher is not enough, and a mutation proved it: a summary that
    # ASSERTS the interesting cause as fact and only later says "check the
    # watcher" still passed. That is #1377's shape exactly — the responder reads
    # a statement, not a question, and goes to the wrong system. The summary must
    # present two causes, not one cause plus a footnote.
    assert any(marker in summary for marker in ("either", "or the", "no data")), (
        f"{uid} ({filename}) names the watcher but still asserts a single cause. "
        "With noDataState: Alerting the rule has two, and the summary has to say so — "
        'lead with "Either … or … stopped reporting", never with the finding as fact.'
    )
