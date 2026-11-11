"""Each step reports warm request capacity apart from its cold connection burst (#3294).

k6 starts every step as a new process, so every connection is new. Run d46f3fbb showed
the first degraded rate was how much of that burst ace1 absorbs, not how many requests
it serves once connections are open (#3102, lesson-736). The step now opens with a
warm-up on the same virtual users: the verdict reads only what follows it, and the
warm-up is reported as the cold figure, with its own knee.
"""

from __future__ import annotations

import contextlib
import json
import pathlib
import re

import pytest

from toolkit.features import load_test as lt
from toolkit.features import load_test_timeline as tl

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (REPO / lt.SCRIPT).read_text(encoding="utf-8")

TREND = {"avg": 2, "med": 1, "p(90)": 3, "p(95)": 4, "p(99)": 5, "max": 6}


def _phase(name: str, count: float, failed: float, p95: float) -> dict:
    tag = f"{{phase:{name}}}"
    metrics = {
        f"http_req_duration{tag}": {"values": {**TREND, "p(95)": p95}},
        f"http_reqs{tag}": {"values": {"count": count, "rate": 1.0}},  # rate is over the whole test: never used
        f"http_req_failed{tag}": {"values": {"rate": failed}},
    }
    metrics |= {f"http_req_{p}{tag}": {"values": {"med": 1, "p(95)": 2, "p(99)": 3, "max": 4}} for p in lt.PHASES}
    return metrics


def _summary(**extra: dict) -> str:
    metrics = {
        "http_req_duration": {"values": {**TREND, "p(95)": 900}},
        "http_reqs": {"values": {"count": 90_000, "rate": 1000.0}},
        "http_req_failed": {"values": {"rate": 0.02}},
        "vus": {"values": {"max": 2000}},
        "dropped_iterations": {"values": {"count": 7}},
        "status_429": {"values": {"count": 0}},
        **_phase("cold", 28_000, 0.05, 2500),
        **_phase("warm", 60_000, 0.0, 1.5),
        **extra,
    }
    return json.dumps(metrics)


class TestTheScriptSplitsOneScenario:
    def test_the_warm_up_runs_on_the_same_virtual_users(self) -> None:
        """Each k6 scenario has its own VU pool, so a second scenario would reopen every connection."""
        assert SCRIPT.count("executor:") == 1
        assert "duration: `${warmup + seconds}s`" in SCRIPT

    def test_each_request_is_tagged_with_its_phase_before_it_is_sent(self) -> None:
        assert "import exec from 'k6/execution'" in SCRIPT
        assert "exec.scenario.startTime" in SCRIPT
        assert "tags: { phase }" in SCRIPT

    def test_every_figure_the_toolkit_reads_is_summarised_per_phase(self) -> None:
        """k6 puts a tagged submetric in the summary only when a threshold names it."""
        listed = set(re.findall(r"'(http_req_\w+|http_reqs)'", SCRIPT.split("const PER_PHASE")[1].split("];")[0]))
        assert listed == {"http_req_duration", "http_reqs", "http_req_failed", *(f"http_req_{p}" for p in lt.PHASES)}

    def test_the_toolkit_passes_the_warm_up(self) -> None:
        target = lt.Target("api", "api.staging.example", "/health", "api")
        assert lt.k6_env(target, "1.2.3.4", 100, 60, None, warmup=30)["LT_WARMUP"] == "30"
        assert lt.k6_env(target, "1.2.3.4", 100, 60, None)["LT_WARMUP"] == "0"


class TestParsing:
    def test_the_step_figures_are_the_warm_ones(self) -> None:
        got = lt.parse_summary(_summary(), warmup=30, seconds=60)
        assert got["requests"] == 60_000
        assert got["achieved_rps"] == 1000.0  # 60,000 over the 60 measured seconds, not k6's whole-test rate
        assert (got["error_rate"], got["p95_ms"]) == (0.0, 1.5)
        assert got["phases"]["connecting"]["p95_ms"] == 2

    def test_the_cold_burst_is_kept_and_named(self) -> None:
        cold = lt.parse_summary(_summary(), warmup=30, seconds=60)["cold"]
        assert (cold["requests"], cold["achieved_rps"]) == (28_000, pytest.approx(933.3, abs=0.1))
        assert (cold["error_rate"], cold["p95_ms"]) == (0.05, 2500)

    def test_what_is_not_tagged_stays_step_wide(self) -> None:
        """A 429 in either phase means the route was not in force; VUs and drops carry no request tag."""
        got = lt.parse_summary(_summary(status_429={"values": {"count": 3}}), warmup=30, seconds=60)
        assert (got["status_429"], got["vus_peak"], got["dropped"]) == (3, 2000, 7)
        assert "status_429" not in got["cold"] and "vus_peak" not in got["cold"]

    def test_without_a_warm_up_the_step_reads_as_before(self) -> None:
        got = lt.parse_summary(_summary(), warmup=0, seconds=60)
        assert (got["requests"], got["achieved_rps"], got["p95_ms"]) == (90_000, 1000.0, 900)
        assert "cold" not in got

    def test_a_cold_phase_with_no_requests_reads_as_zero(self) -> None:
        metrics = {k: v for k, v in json.loads(_summary()).items() if "phase:cold" not in k}
        cold = lt.parse_summary(json.dumps(metrics), warmup=30, seconds=60)["cold"]
        assert (cold["requests"], cold["achieved_rps"], cold["p95_ms"]) == (0, 0.0, 0.0)

    def test_a_summary_without_warm_figures_is_refused(self) -> None:
        metrics = {k: v for k, v in json.loads(_summary()).items() if "phase:warm" not in k}
        with pytest.raises(KeyError):
            lt.parse_summary(json.dumps(metrics), warmup=30, seconds=60)


class TestColdVerdict:
    def _step(self, rate: int, cold: dict, **over: object) -> dict:
        step = {"rate": rate, "status_429": 0, "error_rate": 0.0, "p95_ms": 2.0, "achieved_rps": float(rate)}
        return {**step, "generator_cpu": 10.0, "vus_peak": 9, "cold": cold, **over}

    def test_the_cold_burst_is_judged_by_the_same_limits(self) -> None:
        cold = {"error_rate": 0.05, "p95_ms": 2500.0, "achieved_rps": 900.0}
        assert lt.cold_reasons(self._step(1000, cold), 1000) == ["errors", "latency", "throughput"]

    def test_step_wide_reasons_apply_to_both(self) -> None:
        cold = {"error_rate": 0.0, "p95_ms": 2.0, "achieved_rps": 1000.0}
        assert lt.cold_reasons(self._step(1000, cold, edge_restarts=1), 1000) == ["edge-restart"]

    def test_the_cold_knee_reads_the_cold_reasons(self) -> None:
        steps = [
            {"rate": 800, "reasons": [], "cold_reasons": [], "vus_peak": 1},
            {"rate": 1000, "reasons": [], "cold_reasons": ["latency"], "vus_peak": 2},
            {"rate": 1200, "reasons": ["latency"], "cold_reasons": ["latency"], "vus_peak": 3},
        ]
        assert lt.knee(steps)["first_degraded_rps"] == 1200
        cold = lt.cold_knee(steps)
        assert (cold["last_healthy_rps"], cold["first_degraded_rps"]) == (800, 1000)

    def test_a_step_without_a_warm_up_has_no_cold_knee(self) -> None:
        assert lt.cold_knee([{"rate": 800, "reasons": [], "vus_peak": 1}]) is None


class _Lab(lt.Lab):
    def __init__(self, seen: list) -> None:
        super().__init__(REPO, "kc", "op", "node", "gen")
        self.seen = seen

    def cpu_line(self, _node: str) -> str:
        return "cpu 1 0 0 9 0 0 0"

    def cpu_stat(self, _workload: str) -> str:
        return "throttled_usec 0"

    def pod(self, *_a: object, **_k: object) -> dict:
        return {"metadata": {"uid": "u"}}

    def edge_state(self) -> tuple[str, int]:
        return ("a", 0)

    def ssh(self, node: str, command: str, stdin: str | None = None, timeout: int = 60, options: tuple = ()) -> str:
        self.seen.append(("ssh", timeout))
        return _summary()

    def timeline_readers(self, workload: str, ssh_options: tuple[str, ...] = ()) -> tl.Readers:
        return "readers"  # type: ignore[return-value]

    @contextlib.contextmanager
    def multiplexed(self, nodes: tuple[str, ...], seconds: int):  # type: ignore[no-untyped-def,override]
        self.seen.append(("mux", seconds))
        yield ()


class TestTheStepLastsTheWarmUpToo:
    def _step(self, monkeypatch: pytest.MonkeyPatch, seen: list) -> dict:
        monkeypatch.setattr(lt, "_sample_mid_step", lambda _lab, _w, delay: seen.append(("top", delay)) or ({}, 0))
        monkeypatch.setattr(tl, "sample_timeline", lambda _r, seconds, _every: seen.append(("sample", seconds)) or [])
        target = lt.Target("api", "api.staging.example", "/health", "api")
        return lt.run_step(_Lab(seen), "img", "", target, "1.2.3.4", 1000, 60, None, sample_seconds=2, warmup=30)

    def test_every_duration_covers_warm_up_and_step(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list = []
        self._step(monkeypatch, seen)
        assert ("sample", 30 + 60 + lt.TIMELINE_TAIL_SECONDS) in seen
        assert ("mux", 30 + 60 + lt.TIMELINE_TAIL_SECONDS + lt.MUX_MARGIN_SECONDS) in seen
        assert ("ssh", 30 + 60 + 120) in seen  # k6's own session

    def test_the_pods_are_read_in_the_warm_window(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list = []
        self._step(monkeypatch, seen)
        assert ("top", 30 + lt.TOP_AFTER_SECONDS) in seen

    def test_the_step_carries_both_verdicts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        step = self._step(monkeypatch, [])
        assert step["reasons"] == []  # warm: 1,000/s at 1.5 ms
        assert step["cold_reasons"] == ["errors", "latency", "throughput"]
        assert step["warmup_seconds"] == 30


class TestTheRunRecordsTheWarmUp:
    def test_criteria_and_ramps_name_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from tests.test_load_test import _DyingLab

        passed: list = []

        def step(*_a: object, **kw: object) -> dict:
            passed.append(kw["warmup"])
            return {"rate": 50, "reasons": ["errors"], "cold_reasons": ["errors"], "vus_peak": 1}

        monkeypatch.setattr(lt, "run_step", step)
        monkeypatch.setattr(lt, "_runtime_facts", lambda *_: {})
        monkeypatch.setattr(lt, "wait_for_stable_edge", lambda *_: None)
        monkeypatch.setattr("time.sleep", lambda _: None)
        target = lt.Target("api", "api.example", "/health", "api")
        result = lt.run(_DyingLab(), "img", (target,), "1.2.3.4", 1, 60, 50, warmup=30)
        assert result["criteria"]["warmup_seconds"] == 30
        assert set(passed) == {30}  # the baseline too
        assert result["ramps"][0]["cold_knee"]["first_degraded_rps"] == 50

    def test_a_negative_warm_up_is_refused(self) -> None:
        from tests.test_load_test import _DyingLab

        target = lt.Target("api", "api.example", "/health", "api")
        with pytest.raises(lt.LoadTestRefused):
            lt.run(_DyingLab(), "img", (target,), "1.2.3.4", 1, 60, 50, warmup=-1)


class TestTheReportShowsBoth:
    def _step(self) -> dict:
        figures = dict.fromkeys(("requests", "achieved_rps", "error_rate", "status_429", "dropped", "vus_peak"), 0)
        figures |= dict.fromkeys(("avg_ms", "p50_ms", "p90_ms", "p95_ms", "p99_ms", "max_ms", "throttled_ms"), 0.0)
        cold = {"requests": 28_000, "achieved_rps": 933.3, "error_rate": 0.05, "p95_ms": 2500.0, "p99_ms": 4000.0}
        return {
            **figures, "rate": 1000, "node_cpu": 1.0, "generator_cpu": 1.0, "node_mem_available_mb": 1,
            "pods_top": {}, "reasons": [], "cold": cold, "cold_reasons": ["errors", "latency"],
        }  # fmt: skip

    def test_a_ramp_shows_its_cold_knee_and_cold_figures(self) -> None:
        ramp = {"target": "api", "repeat": 1, "knee": {}, "cold_knee": {"first_degraded_rps": 1000}, "steps": []}
        ramp["steps"] = [self._step()]
        text = lt.render({"baseline": [], "ramps": [ramp]})
        assert 'Cold knee: `{"first_degraded_rps": 1000}`' in text
        assert "| 1000 | 933.3 | 28000 | 2500.00 | 4000.00 | 5.00% | errors,latency |" in text

    def test_a_report_of_an_older_run_has_no_cold_section(self) -> None:
        step = {k: v for k, v in self._step().items() if k not in ("cold", "cold_reasons")}
        text = lt.render({"baseline": [], "ramps": [{"target": "api", "repeat": 1, "knee": {}, "steps": [step]}]})
        assert "Cold" not in text and "cold" not in text


def test_the_command_defaults_to_the_declared_warm_up() -> None:
    import inspect

    from toolkit.cli import infra

    default = inspect.signature(infra.load_test_run).parameters["warmup_seconds"].default
    assert default == lt.WARMUP_SECONDS


def test_make_passes_the_warm_up() -> None:
    target = (REPO / "Makefile").read_text(encoding="utf-8").split("\nload-test:")[1].split("\n\n")[0]
    assert "$(if $(WARMUP_SECONDS),--warmup-seconds $(WARMUP_SECONDS))" in target
