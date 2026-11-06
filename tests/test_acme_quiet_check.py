"""OBS-033 (#2195): the ACME failure rule stays quiet on Traefik's heartbeat.

The rule is read from the rendered overlay, never copied here, so a future edit
to its LogQL is what these checks run against.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

from toolkit.features import acme_quiet_check as q

ROOT = Path(__file__).resolve().parents[1]


def _rendered(env: str) -> list[dict]:
    out = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / "infra" / "k8s" / "overlays" / env)],
        capture_output=True,
        text=True,
        check=True,
    )
    return [doc for doc in yaml.safe_load_all(out.stdout) if doc]


def _docs(expr: str, window_from: int = 600) -> list[dict]:
    rules = {
        "groups": [
            {
                "rules": [
                    {
                        "uid": q.RULE_UID,
                        "data": [{"refId": "A", "relativeTimeRange": {"from": window_from}, "model": {"expr": expr}}],
                    }
                ]
            }
        ]
    }
    return [
        {"kind": "Secret", "metadata": {"name": "x"}},
        {"kind": "ConfigMap", "metadata": {"name": "grafana-alerting-abc"}, "data": {"rules.yaml": yaml.dump(rules)}},
    ]


EXPR = 'sum by (domain) (count_over_time({container="traefik"} |~ "(?i)acme" |~ "fail" [10m]))'


class TestRuleQuery:
    @pytest.mark.parametrize("env", ["staging", "prod"])
    def test_the_rule_is_found_in_each_rendered_overlay(self, env: str) -> None:
        rule = q.rule_query(_rendered(env))
        assert rule.selector == '{container="traefik"}'
        assert rule.window_s == 600

    def test_selector_and_log_query_come_from_the_expression(self) -> None:
        rule = q.rule_query(_docs(EXPR))
        assert rule.expr == EXPR
        assert rule.selector == '{container="traefik"}'
        assert rule.log_query == '{container="traefik"} |~ "(?i)acme" |~ "fail"'

    def test_a_range_that_disagrees_with_the_query_window_is_refused(self) -> None:
        # The [10m] in the LogQL and relativeTimeRange.from are two declarations
        # of one window; evaluating one while Grafana uses the other proves nothing.
        with pytest.raises(q.QuietCheckError, match="window"):
            q.rule_query(_docs(EXPR, window_from=300))

    def test_a_missing_rule_is_an_error_not_a_quiet_result(self) -> None:
        with pytest.raises(q.QuietCheckError, match=q.RULE_UID):
            q.rule_query([{"kind": "ConfigMap", "metadata": {"name": "grafana-alerting-x"}, "data": {}}])


class TestVerdict:
    def test_no_heartbeat_found_is_not_measured(self) -> None:
        result = q.verdict(heartbeat_ns=None, heartbeats_in_window=0, alert_series=[], matched_lines=[])
        assert not result.measured and not result.ok
        assert "no heartbeat" in result.reason

    def test_a_window_the_selector_cannot_see_the_heartbeat_in_is_not_measured(self) -> None:
        # An empty answer from a selector that sees nothing is not quiet.
        result = q.verdict(heartbeat_ns=1, heartbeats_in_window=0, alert_series=[], matched_lines=[])
        assert not result.measured and not result.ok

    def test_heartbeat_in_window_and_empty_result_is_quiet(self) -> None:
        result = q.verdict(heartbeat_ns=1, heartbeats_in_window=1, alert_series=[], matched_lines=[])
        assert result.measured and result.quiet and result.ok

    def test_a_matched_heartbeat_is_a_rule_regression(self) -> None:
        line = "INF Testing certificate renew... acmeCA=x"
        result = q.verdict(heartbeat_ns=1, heartbeats_in_window=1, alert_series=[{"value": [0, "1"]}], matched_lines=[line])
        assert result.measured and not result.quiet
        assert "matches the heartbeat" in result.reason

    def test_a_matched_boot_line_is_a_rule_regression(self) -> None:
        line = "INF Starting provider *acme.Provider"
        result = q.verdict(heartbeat_ns=1, heartbeats_in_window=1, alert_series=[{"value": [0, "1"]}], matched_lines=[line])
        assert "matches the heartbeat" in result.reason

    def test_a_real_failure_in_the_window_is_not_called_a_regression(self) -> None:
        line = "ERR Unable to obtain ACME certificate domains=[\"x.kubelab.local\"]"
        result = q.verdict(heartbeat_ns=1, heartbeats_in_window=1, alert_series=[{"value": [0, "1"]}], matched_lines=[line])
        assert not result.ok
        assert "real ACME failure" in result.reason


class _Loki:
    def __init__(self, heartbeat_ns: int | None, control: str, alert: list, lines: list[str]) -> None:
        self.heartbeat_ns, self.control, self.alert, self.lines = heartbeat_ns, control, alert, lines
        self.instant: list[tuple[str, int]] = []

    def query_range(self, query: str, **kwargs):  # noqa: ANN003, ANN201
        if q.HEARTBEAT in query:
            return [] if self.heartbeat_ns is None else [{"ts_ns": self.heartbeat_ns, "line": "hb"}]
        assert kwargs["end_ns"] == self.heartbeat_ns + q.EVAL_OFFSET_S * 10**9
        return [{"ts_ns": 0, "line": line} for line in self.lines]

    def query_instant(self, query: str, at_ns: int):  # noqa: ANN201
        self.instant.append((query, at_ns))
        if "|= " in query:
            return [{"value": [0, self.control]}]
        return self.alert


class TestRun:
    def test_it_evaluates_the_rule_one_minute_after_the_heartbeat(self) -> None:
        loki = _Loki(heartbeat_ns=5 * 10**9, control="1", alert=[], lines=[])
        result = q.run_acme_quiet_check(loki, _docs(EXPR))
        assert result.ok
        assert (EXPR, 65 * 10**9) in loki.instant

    def test_it_reads_the_matching_lines_when_the_rule_answers(self) -> None:
        loki = _Loki(5 * 10**9, "1", [{"value": [0, "1"]}], ["INF Testing certificate renew..."])
        result = q.run_acme_quiet_check(loki, _docs(EXPR))
        assert not result.ok and result.matched_lines

    def test_no_heartbeat_skips_the_evaluation(self) -> None:
        loki = _Loki(None, "0", [], [])
        result = q.run_acme_quiet_check(loki, _docs(EXPR))
        assert not result.measured and loki.instant == []
