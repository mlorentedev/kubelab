"""Every field an alert `unwrap`s must be emitted as a number (OBS-018, #1377).

The chain is watcher -> JSON log line -> Vector -> Loki -> Grafana Alerting, and
it has one silent joint: LogQL's `unwrap` converts a label to a float, so a field
emitted as a JSON **boolean** is dropped rather than rejected. The query then
returns no data, `noDataState: Alerting` fires the rule, and the notification
asserts whatever its summary happens to say.

That shipped on 2026-08-23 and fired falsely in both environments for a day and a
half. The reason it survived review is worth keeping in mind while reading these
tests: the file emits two metrics, and only the one written with jq was wrong —

    healthy: (.status.phase == "Bound")        # jq   -> true   -> DROPPED
    "\"healthy\":$((USED_PCT < 90))"           # bash -> 1      -> fine

Each half is individually reasonable. The defect only exists in the relationship
between an emitter and a query in a different file, which is exactly the kind of
thing a human reviewer is worst at and a test is best at.
"""

from __future__ import annotations

import pathlib
import re

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVICES = REPO_ROOT / "infra/k8s/base/services"
RULES_DIR = SERVICES / "grafana-alerting"

# `| unwrap <field>` — the field whose type has to be a number.
_UNWRAP = re.compile(r"\|\s*unwrap\s+([a-z_][a-z0-9_]*)", re.IGNORECASE)

# A jq object entry whose value is a bare comparison: `healthy: (.x == "y")`.
# jq renders that as a JSON boolean. `if ... then 1 else 0 end` does not match,
# which is the correction this guard exists to keep in place.
def _boolean_jq_assignment(field: str) -> re.Pattern[str]:
    return re.compile(rf"^\s*{re.escape(field)}\s*:\s*\((?![^)]*\bif\b)[^)]*[=!]=[^)]*\)", re.MULTILINE)


def _unwrapped_fields() -> set[str]:
    fields: set[str] = set()
    for rule_file in sorted(RULES_DIR.glob("*.yaml")):
        fields.update(_UNWRAP.findall(rule_file.read_text(encoding="utf-8")))
    return fields


def _watchers() -> list[pathlib.Path]:
    return [p for p in sorted(SERVICES.glob("*watcher*.yaml"))]


def test_the_rules_unwrap_something_at_all() -> None:
    """Guards against the guard passing vacuously.

    If `unwrap` is ever replaced wholesale by a label filter, the tests below
    would pass by finding nothing to check — which reads identical to passing
    because everything is correct.
    """
    assert _unwrapped_fields(), f"no `| unwrap <field>` found in {RULES_DIR}; this suite is asserting nothing"


def test_watchers_exist_to_be_checked() -> None:
    assert _watchers(), f"no *watcher*.yaml under {SERVICES}; this suite is asserting nothing"


@pytest.mark.parametrize("watcher", _watchers(), ids=lambda p: p.name)
def test_no_unwrapped_field_is_emitted_as_a_jq_boolean(watcher: pathlib.Path) -> None:
    body = watcher.read_text(encoding="utf-8")

    for field in sorted(_unwrapped_fields()):
        match = _boolean_jq_assignment(field).search(body)
        assert match is None, (
            f"{watcher.name} emits `{field}` as a jq boolean: {match.group(0).strip()!r}\n"
            f"An alert rule calls `| unwrap {field}`, and unwrap needs a float — a boolean is "
            f"DROPPED, the query returns no data, and `noDataState: Alerting` fires a rule whose "
            f"summary blames the wrong thing. Emit a number: "
            f"`{field}: (if <cond> then 1 else 0 end)`."
        )


def test_the_pvc_health_field_is_numeric_specifically() -> None:
    """The exact regression from #1377, pinned by name rather than by pattern.

    The generic test above would also catch it, and this one exists because a
    pattern can be loosened by someone who does not know which instance it was
    written for.
    """
    body = (SERVICES / "disk-watcher.yaml").read_text(encoding="utf-8")

    assert 'healthy: (.status.phase == "Bound")' not in body, "the #1377 regression is back, verbatim"
    assert 'healthy: (if .status.phase == "Bound" then 1 else 0 end)' in body


def test_the_no_data_case_is_admitted_in_the_summary() -> None:
    """`noDataState: Alerting` means the rule fires for two different reasons.

    A summary that names only one of them turns a silent watcher into a
    confident, wrong diagnosis — the operational half of #1377.
    """
    body = (RULES_DIR / "disk-rules.yaml").read_text(encoding="utf-8")
    pvc_rule = body[body.index("obs015-pvc-unbound-failure") :]
    summary = pvc_rule[pvc_rule.index("summary:") : pvc_rule.index("runbook_url:")].lower()

    assert "noDataState: Alerting" in pvc_rule, "if this rule stops alerting on no data, revisit the summary too"
    assert "no data" in summary or "stopped reporting" in summary, (
        "the summary asserts a storage failure without admitting the rule also fires when the "
        "watcher goes silent"
    )
