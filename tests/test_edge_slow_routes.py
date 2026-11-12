"""Which routes take long, per router, from the edge's slow-request access log (OPS-065, #3076).

The bound on a backend's response headers is sized from this report, so it has to
tell "no slow request was seen" apart from "this route was never asked", and say
how far the log reaches back: prod's Loki keeps 168 h, so a seven-day reading is
always at the edge of what is left.
"""

from __future__ import annotations

import pathlib

import pytest

from toolkit.features import edge_slow_routes as esr

REPO = pathlib.Path(__file__).resolve().parents[1]
WEB = "kubelab-web-9a007d33a769b7b0fc2d@kubernetescrd"
GITEA = "kubelab-gitea-4d0b79276f78ba8cd4d5@kubernetescrd"


def _vec(router: str, value: float, **labels: str) -> dict:
    return {"metric": {"RouterName": router, **labels}, "value": [0, str(value)]}


class TestTheQueries:
    def test_slow_lines_are_selected_by_the_log_threshold_not_by_status(self) -> None:
        """A fast 5xx is logged too (statuscodes 500-599); it is not a slow request."""
        q = esr.queries("7d", [30], logged_from_ns=1_000_000_000)
        assert "Duration >= 1000000000" in q["count"]
        assert all('{container="traefik"}' in v for v in q.values())

    def test_the_distribution_is_read_from_the_backend_time(self) -> None:
        q = esr.queries("7d", [30], logged_from_ns=1_000_000_000)
        assert "unwrap OriginDuration" in q["p99"]
        assert q["p99"].startswith("quantile_over_time(0.99,")
        assert "[7d]" in q["max"]

    def test_each_bound_counts_the_requests_past_it(self) -> None:
        q = esr.queries("7d", [10, 60], logged_from_ns=1_000_000_000)
        assert "OriginDuration > 10000000000" in q["over_10"]
        assert "OriginDuration > 60000000000" in q["over_60"]

    def test_statuses_are_counted_per_router(self) -> None:
        q = esr.queries("7d", [30], logged_from_ns=1_000_000_000)
        assert "by (RouterName, DownstreamStatus)" in q["status"]

    def test_nothing_reads_a_field_the_log_does_not_keep(self) -> None:
        """The log keeps no path or client address (SEC-021); a query on one would read empty, not fail."""
        text = " ".join(esr.queries("7d", [30], logged_from_ns=1).values())
        assert "RequestPath" not in text and "ClientHost" not in text


class TestTheThreshold:
    def test_it_is_read_from_the_role_that_sets_it(self) -> None:
        assert esr.logged_from_ns(REPO) == 1_000_000_000

    @pytest.mark.parametrize(("text", "ns"), [("1s", 10**9), ("500ms", 5 * 10**8), ("2m", 120 * 10**9)])
    def test_go_durations_parse(self, text: str, ns: int) -> None:
        assert esr.go_duration_ns(text) == ns


class TestTheRows:
    def _results(self) -> dict:
        return {
            "count": [_vec(WEB, 37), _vec(GITEA, 571)],
            "p50": [_vec(WEB, 3.21e9), _vec(GITEA, 1.6e9)],
            "p99": [_vec(WEB, 25.55e9), _vec(GITEA, 11.65e9)],
            "max": [_vec(WEB, 34.63e9), _vec(GITEA, 6872.69e9)],
            "over_30": [_vec(WEB, 2), _vec(GITEA, 3)],
            "status": [
                _vec(GITEA, 570, DownstreamStatus="200"),
                _vec(GITEA, 1, DownstreamStatus="502"),
                _vec(WEB, 37, DownstreamStatus="200"),
            ],
        }

    def test_a_router_is_named_by_its_ingressroute(self) -> None:
        rows = esr.summarize(self._results(), ["web", "gitea"], [30])
        web = next(r for r in rows if r.route == "web")
        assert (web.router, web.count, web.p99_s, web.max_s) == ("9a007d33a769b7b0fc2d", 37, 25.55, 34.63)
        assert web.over == {30: 2}

    def test_statuses_are_kept_per_router(self) -> None:
        rows = esr.summarize(self._results(), ["web", "gitea"], [30])
        assert next(r for r in rows if r.route == "gitea").statuses == {"200": 570, "502": 1}

    def test_a_route_with_no_slow_line_reads_as_no_sample(self) -> None:
        rows = esr.summarize(self._results(), ["web", "gitea", "api"], [30])
        api = next(r for r in rows if r.route == "api")
        assert api.count == 0 and api.router is None and api.p99_s is None

    def test_a_router_past_no_bound_reads_zero_not_missing(self) -> None:
        """Loki returns no series for a count of zero."""
        results = self._results()
        results["over_30"] = [_vec(GITEA, 3)]
        web = next(r for r in esr.summarize(results, ["web", "gitea"], [30]) if r.route == "web")
        assert web.over == {30: 0}

    def test_a_router_from_no_declared_route_is_still_shown(self) -> None:
        rows = esr.summarize(self._results(), ["web"], [30])
        assert any(r.route == "gitea" and r.declared is False for r in rows)

    def test_rows_are_ordered_longest_first(self) -> None:
        rows = esr.summarize(self._results(), ["web", "gitea", "api"], [30])
        assert [r.route for r in rows] == ["gitea", "web", "api"]


class TestTheReport:
    def test_it_states_what_the_figures_are(self) -> None:
        rows = esr.summarize(TestTheRows()._results(), ["web", "gitea", "api"], [30])
        text = esr.render(rows, window="7d", bounds=[30], logged_from_ns=10**9, days=[(f"2026-11-0{d}", 1) for d in range(5, 9)])
        assert "OriginDuration" in text and "upper bound" in text
        assert "no sample" in text
        assert "| gitea | 9a007d33" not in text  # router column is the router's own suffix
        assert "| gitea |" in text and "> 30 s" in text

    def test_it_says_how_far_back_the_log_reaches(self) -> None:
        text = esr.render([], window="7d", bounds=[30], logged_from_ns=10**9, days=[("2026-11-05", 12), ("2026-11-06", 900)])
        assert "2026-11-05" in text and "2 days" in text


class TestTheCommand:
    def test_make_runs_it_against_prod_by_default(self) -> None:
        make = (REPO / "Makefile").read_text(encoding="utf-8")
        assert "obs slow-routes" in make
        block = make.split("edge-slow-routes:")[1].split("\n\n")[0]
        assert "prod" in block
