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

import pytest
import yaml

from tests.test_alerting_unwrap_grouping import ALERTING_DIR, CRONJOB_CONTAINERS


def _rules_over_cronjob_streams() -> list[tuple[str, str, dict]]:
    """(file, uid, rule) for every rule whose query reads a CronJob container."""
    found: list[tuple[str, str, dict]] = []
    for path in sorted(ALERTING_DIR.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text()) or {}
        for group in doc.get("groups") or []:
            for rule in group.get("rules") or []:
                queries = "".join(
                    str((item.get("model") or {}).get("expr", "")) for item in rule.get("data") or []
                )
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
    """
    rule = next(r for f, u, r in _rules_over_cronjob_streams() if f == filename and u == uid)
    assert rule.get("noDataState") == "Alerting", (
        f"{uid} ({filename}) has noDataState={rule.get('noDataState')!r}. It reads a stream "
        "produced by a single CronJob, so no-data means the watcher stopped — not that the "
        "thing being watched is well. If this rule genuinely should tolerate silence (an "
        "on-demand node per ADR-028, say), it must not share a stream with one that does not."
    )


@pytest.mark.parametrize(
    ("filename", "uid"),
    [(f, u) for f, u, _ in _rules_over_cronjob_streams()],
    ids=[f"{u}" for _, u, _ in _rules_over_cronjob_streams()],
)
def test_the_summary_names_the_watcher_as_a_cause(filename: str, uid: str) -> None:
    """`noDataState: Alerting` gives the rule two causes, and a summary naming
    only the interesting one sends the responder to the wrong system.

    Not hypothetical: #1377 ran for a day and a half because the summary said a
    storage backend was preventing provisioning while every PVC was Bound and
    the real fault was a query that could not parse its own input. Trading a
    silent failure for a misleading alert is not a fix.
    """
    rule = next(r for f, u, r in _rules_over_cronjob_streams() if f == filename and u == uid)
    summary = str((rule.get("annotations") or {}).get("summary", "")).lower()
    assert "watcher" in summary or "reporting" in summary, (
        f"{uid} ({filename}) alerts on no-data but its summary does not mention that the "
        "watcher stopping is one of the two causes. The responder needs the cheap check "
        "first, in the alert text — not in a runbook they open after chasing the other cause."
    )
