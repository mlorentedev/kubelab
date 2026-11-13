"""CONSOLE-004 AC6 (#3387): a forge console source not read within its bound alerts.

The bound and the window are derived from the api's own periods, so changing how often
the reconciler reads cannot leave the rule measuring something else. GitHub sources page
in prod; Gitea sources are read from the on-demand Beelink and reach the log tier only.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from tests.test_forge_review_failed_route import _policy, _receivers

REPO = Path(__file__).resolve().parents[1]
RULES = REPO / "infra/k8s/base/services/grafana-alerting/forge-rules.yaml"
RECONCILE = REPO / "apps/api/src/internal/forge/reconcile.go"
RUNBOOK = REPO / "docs/runbooks/forge-console-operations.md"

GITHUB_UID = "console004-github-source-stale"
GITEA_UID = "console004-gitea-source-stale"


def _rule(uid: str) -> dict:
    groups = yaml.safe_load(RULES.read_text(encoding="utf-8"))["groups"]
    rules = [r for g in groups for r in g["rules"] if r["uid"] == uid]
    assert len(rules) == 1, f"no single rule {uid}"
    return rules[0]


def _expr(rule: dict) -> str:
    return next(d for d in rule["data"] if d["refId"] == "A")["model"]["expr"]


def _period_minutes(name: str) -> int:
    match = re.search(rf"const {name} = (\d+ \* )?time\.Minute", RECONCILE.read_text(encoding="utf-8"))
    assert match, f"{name} not found in {RECONCILE.name}"
    return int(match.group(1).split()[0]) if match.group(1) else 1


@pytest.mark.parametrize(("uid", "forge"), [(GITHUB_UID, "github"), (GITEA_UID, "gitea")])
def test_each_rule_reads_its_own_forge_freshness(uid: str, forge: str) -> None:
    expr = _expr(_rule(uid))
    assert 'event="forge_source_freshness"' in expr
    assert f'source=~"{forge}:.+"' in expr
    assert "unwrap age_seconds" in expr and "max by (source)" in expr


@pytest.mark.parametrize("uid", [GITHUB_UID, GITEA_UID])
def test_the_bound_is_two_missed_full_passes(uid: str) -> None:
    rule = _rule(uid)
    threshold = next(d for d in rule["data"] if d["refId"] == rule["condition"])
    (condition,) = threshold["model"]["conditions"]
    assert condition["evaluator"] == {"type": "gt", "params": [2 * _period_minutes("ReconcilePeriod") * 60]}


@pytest.mark.parametrize("uid", [GITHUB_UID, GITEA_UID])
def test_the_window_holds_three_full_passes(uid: str) -> None:
    (window,) = re.findall(r"\[(\d+)m\]", _expr(_rule(uid)))
    assert int(window) >= 3 * _period_minutes("ReconcilePeriod")


def test_only_the_github_rule_alerts_on_a_silent_api() -> None:
    assert _rule(GITHUB_UID)["noDataState"] == "Alerting"
    assert _rule(GITEA_UID)["noDataState"] == "OK"


def test_github_pages_in_prod_and_gitea_never_does() -> None:
    github, gitea = _rule(GITHUB_UID)["title"], _rule(GITEA_UID)["title"]
    assert _receivers(_policy("prod"), {"alertname": github}) == ["apprise-page"]
    for env in ("staging", "prod"):
        assert _receivers(_policy(env), {"alertname": gitea}) == ["apprise-log"], env


@pytest.mark.parametrize("uid", [GITHUB_UID, GITEA_UID])
def test_the_runbook_anchor_exists(uid: str) -> None:
    anchor = _rule(uid)["annotations"]["runbook_url"].strip().rsplit("#", 1)[1]
    headings = re.findall(r"^#+ (.+)$", RUNBOOK.read_text(encoding="utf-8"), re.MULTILINE)
    assert anchor in {re.sub(r"[^a-z0-9 -]", "", h.lower()).replace(" ", "-") for h in headings}
