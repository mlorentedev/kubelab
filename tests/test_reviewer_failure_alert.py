"""A forge review that failed must reach the operator (TOOL-093, #1957).

When every model fails, PR-Agent logs `Failed to review PR` and publishes
nothing, so from the PR it looks like a webhook that never arrived. The rule
that reads that line is the only thing that tells the two apart, so it is
pinned here: what it matches, what it does on silence, and that the matcher
agrees with a line PR-Agent really wrote.
"""

from __future__ import annotations

import json
import pathlib

import yaml

from tests.test_alerting_unwrap_grouping import ALERTING_DIR

UID = "tool093-reviewer-failed"

# Copied from prod Loki, 2026-10-16 08:01Z (container=pr-agent), nothing else trimmed but the traceback.
REAL_FAILURE_LINE = json.dumps(
    {
        "text": "Failed to review PR: Failed to generate prediction with any model of "
        "['openai/mimo-v2.6-flash', 'openai/deepseek-v4-flash']\n",
        "record": {
            "extra": {"command": "review", "pr_url": "https://gitea.kubelab.live/personal/imagesensortool/pulls/29"},
            "level": {"name": "ERROR"},
        },
    }
)


def _rule() -> dict:
    for path in sorted(pathlib.Path(ALERTING_DIR).glob("*.yaml")):
        for group in (yaml.safe_load(path.read_text()) or {}).get("groups") or []:
            for rule in group.get("rules") or []:
                if rule.get("uid") == UID:
                    return rule
    raise AssertionError(f"no rule {UID} under {ALERTING_DIR}")


def _expr(rule: dict) -> str:
    return next(i["model"]["expr"] for i in rule["data"] if i["refId"] == "A")


def test_the_rule_reads_the_reviewers_failure_line_per_pull_request() -> None:
    expr = _expr(_rule())
    assert '{container="pr-agent"}' in expr
    assert "Failed to review PR" in expr
    assert "sum by (pr)" in expr, "one instance per PR, not one for the fleet"


def test_the_matcher_agrees_with_a_line_the_reviewer_really_wrote() -> None:
    """The rule filters on the text the reviewer logs. If a PR-Agent upgrade rewords it,
    this fixture is what to refresh from Loki, in the same change as the rule."""
    needle = "Failed to review PR"
    assert f'|= "{needle}"' in _expr(_rule())
    assert needle in json.loads(REAL_FAILURE_LINE)["text"]
    assert json.loads(REAL_FAILURE_LINE)["record"]["extra"]["pr_url"].startswith("https://")


def test_silence_is_health_for_this_rule() -> None:
    """A query that matches nothing returns no series, and that is the good state: nothing failed."""
    rule = _rule()
    assert rule["noDataState"] == "OK"
    assert rule["execErrState"] == "Error", "a broken query must not read as healthy"


def test_the_summary_tells_the_author_what_to_do_and_what_not() -> None:
    summary = " ".join(_rule()["annotations"]["summary"].split())
    assert "push" in summary.lower(), "a push is the only retry the forge reviewer honours (#1963)"
    assert "/review" not in summary or "ignored" in summary
