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
        encoding="utf-8",
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


ALERT = [{"value": [0, "1"]}]


class TestVerdict:
    def test_no_line_found_is_not_measured(self) -> None:
        result = q.verdict(q.HEARTBEAT, None, [], [])
        assert not result.measured and not result.quiet
        assert "no `Testing certificate renew` line" in result.reason

    def test_line_in_window_and_empty_result_is_quiet(self) -> None:
        result = q.verdict(q.HEARTBEAT, 1, [], [])
        assert result.measured and result.quiet
        assert result.at_ns == 1 + q.EVAL_OFFSET_S * 10**9

    @pytest.mark.parametrize("line", ["INF Testing certificate renew... acmeCA=x", "INF Starting provider *acme.Provider"])
    def test_a_matched_traefik_line_is_a_rule_regression(self, line: str) -> None:
        result = q.verdict(q.BOOT_LINE, 1, ALERT, [line])
        assert result.measured and not result.quiet
        assert "regression of the rule" in result.reason

    def test_a_real_failure_in_the_window_is_not_called_a_regression(self) -> None:
        line = 'ERR Unable to obtain ACME certificate domains=["x.kubelab.local"]'
        result = q.verdict(q.HEARTBEAT, 1, ALERT, [line])
        assert not result.quiet
        assert "real ACME failure" in result.reason


class _Loki:
    """Each anchor's newest line at its own instant; the rule answers per instant."""

    def __init__(self, newest: dict[str, int | None], alert_at: dict[int, list], lines: list[str]) -> None:
        self.newest, self.alert_at, self.lines = newest, alert_at, lines
        self.instant: list[tuple[str, int]] = []
        self.sample: list[dict] = []

    def query_range(self, query: str, **kwargs):  # noqa: ANN003, ANN201
        for anchor, ts in self.newest.items():
            if f'|= "{anchor}"' in query:
                assert kwargs["since"] == q.LOOKBACK
                return [] if ts is None else [{"ts_ns": ts, "line": anchor}]
        self.sample.append(kwargs)
        return [{"ts_ns": 0, "line": line} for line in self.lines]

    def query_instant(self, query: str, at_ns: int):  # noqa: ANN201
        self.instant.append((query, at_ns))
        return self.alert_at.get(at_ns, [])


S = 10**9


class TestRun:
    def test_the_rule_is_evaluated_one_minute_after_each_anchor(self) -> None:
        loki = _Loki({q.HEARTBEAT: 5 * S, q.BOOT_LINE: 100 * S}, {}, [])
        result = q.run_acme_quiet_check(loki, _docs(EXPR))
        assert result.ok
        assert loki.instant == [(EXPR, 65 * S), (EXPR, 160 * S)]

    def test_quiet_on_the_heartbeat_but_matching_the_boot_line_fails(self) -> None:
        # The boot line rarely shares the heartbeat's window, so it needs its own instant.
        loki = _Loki({q.HEARTBEAT: 5 * S, q.BOOT_LINE: 100 * S}, {160 * S: ALERT}, ["INF Starting provider *acme.Provider"])
        result = q.run_acme_quiet_check(loki, _docs(EXPR))
        assert not result.ok
        assert [a.quiet for a in result.anchors] == [True, False]
        assert loki.sample[0]["end_ns"] == 160 * S and loki.sample[0]["limit"] == q.SAMPLE_LIMIT

    def test_no_boot_line_in_retention_is_not_a_pass(self) -> None:
        loki = _Loki({q.HEARTBEAT: 5 * S, q.BOOT_LINE: None}, {}, [])
        result = q.run_acme_quiet_check(loki, _docs(EXPR))
        assert not result.ok
        assert [a.measured for a in result.anchors] == [True, False]
        assert loki.instant == [(EXPR, 65 * S)]

    def test_lookback_is_lokis_retention(self) -> None:
        loki_yaml = (ROOT / "infra" / "k8s" / "base" / "services" / "loki.yaml").read_text()
        assert f"retention_period: {q.LOOKBACK}" in loki_yaml
