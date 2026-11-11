"""Each load-test step carries a timeline, so what moves first at the knee can be read (#3102).

A step's figures are totals over 60 s. They say Traefik's CPU and k6's `waiting` rose at
the degraded step, not which rose first, and the candidates for the stall (GC in Traefik,
other pods on the node, softirq, conntrack, the generator) can only be told apart by order.
The timeline reads what staging already exposes and changes nothing on the cluster.
"""

from __future__ import annotations

import pathlib
import subprocess

import pytest

from toolkit.features import load_test as lt
from toolkit.features import load_test_timeline as tl

REPO = pathlib.Path(__file__).resolve().parents[1]

EDGE_METRICS = """\
# HELP go_gc_duration_seconds A summary of the wall-time pause (stop-the-world) duration in garbage collection cycles.
go_gc_duration_seconds{quantile="1"} 0.0023
go_gc_duration_seconds_sum 0.100
go_gc_duration_seconds_count 500
go_goroutines 264
go_memstats_alloc_bytes_total 1.0e+09
go_memstats_heap_inuse_bytes 3.4e+07
process_cpu_seconds_total 224.0
traefik_open_connections{entrypoint="metrics",protocol="TCP"} 1
traefik_open_connections{entrypoint="websecure",protocol="TCP"} 40
traefik_entrypoint_request_duration_seconds_count{code="200",entrypoint="websecure",method="GET",protocol="http"} 9000
traefik_entrypoint_request_duration_seconds_count{code="504",entrypoint="websecure",method="GET",protocol="http"} 1000
traefik_entrypoint_request_duration_seconds_sum{code="200",entrypoint="websecure",method="GET",protocol="http"} 9.0
traefik_entrypoint_request_duration_seconds_sum{code="504",entrypoint="websecure",method="GET",protocol="http"} 1.0
traefik_entrypoint_request_duration_seconds_count{code="200",entrypoint="web",method="GET",protocol="http"} 77
"""


def _node(
    user: int, idle: int, softirq: int, edge_usec: int | None, work_usec: int | None, conntrack: int = 400
) -> str:
    """/proc/stat with two CPUs, then the conntrack count and the two cgroups' cpu.stat."""
    half = f"{user // 2} 0 0 {idle // 2} 0 0 {softirq // 2} 0 0 0"
    stat = f"cpu  {user} 0 0 {idle} 0 0 {softirq} 0 0 0\ncpu0 {half}\ncpu1 {half}\nintr 1 2 3"
    edge = "" if edge_usec is None else f"usage_usec {edge_usec}\nnr_throttled 0"
    work = "" if work_usec is None else f"usage_usec {work_usec}\nnr_throttled 0"
    return tl.SEPARATOR.join([stat, str(conntrack), edge, work])


class TestParse:
    def test_edge_keeps_the_runtime_and_only_the_public_entrypoint(self) -> None:
        edge = tl.parse_edge(EDGE_METRICS)
        assert edge["go_gc_duration_seconds_count"] == 500
        assert edge["traefik_open_connections"] == 40  # the metrics entrypoint's own connection is not load
        assert edge["traefik_entrypoint_request_duration_seconds_count"] == 10000  # every code, websecure only
        assert edge["traefik_entrypoint_request_duration_seconds_sum"] == 10.0

    def test_node_reads_every_cpu_and_both_cgroups(self) -> None:
        node = tl.parse_node(_node(100, 300, 20, 5_000_000, 1_000_000))
        assert set(node["cpus"]) == {"cpu", "cpu0", "cpu1"}
        assert (node["conntrack"], node["edge_usec"], node["workload_usec"]) == (400, 5_000_000, 1_000_000)

    def test_a_cgroup_that_is_gone_reads_as_unknown_not_zero(self) -> None:
        node = tl.parse_node(_node(100, 300, 20, None, 1_000_000))
        assert node["edge_usec"] is None


class TestInterval:
    def _sample(self, t: float, edge: dict | None, node: dict | None, gen: list[int] | None = None) -> dict:
        return {"t": t, "edge": edge, "node": node, "generator": gen}

    def test_rates_over_one_interval(self) -> None:
        a = tl.parse_edge(EDGE_METRICS)
        b = dict(a)
        b |= {
            "go_gc_duration_seconds_count": 510,  # 10 cycles in 2 s
            "go_gc_duration_seconds_sum": 0.104,  # 4 ms of stop-the-world
            "go_memstats_alloc_bytes_total": 1.0e9 + 200e6,
            "process_cpu_seconds_total": 230.0,  # 6 CPU-seconds in 2 s
            "traefik_entrypoint_request_duration_seconds_count": 12000,
            "traefik_entrypoint_request_duration_seconds_sum": 30.0,
        }
        n1 = tl.parse_node(_node(1000, 3000, 100, 10_000_000, 2_000_000))
        n2 = tl.parse_node(_node(1600, 3200, 300, 15_000_000, 2_500_000))
        row = tl.interval(self._sample(10.0, a, n1, [10, 0, 0, 90]), self._sample(12.0, b, n2, [30, 0, 0, 170]), 10.0)
        assert row["t"] == 2.0
        assert row["edge_rps"] == 1000
        assert row["edge_mean_ms"] == 10.0  # 20 s over 2,000 requests
        assert row["gc_per_s"] == 5
        assert row["gc_pause_ms"] == pytest.approx(4.0)
        assert row["alloc_mb_s"] == 100
        assert row["traefik_cores"] == 3.0
        assert row["open_connections"] == 40
        # 1,000 jiffies elapsed over 2 CPUs: 800 busy -> 1.6 cores, 200 of them softirq -> 0.4 cores.
        assert row["node_cores"] == 1.6
        assert row["softirq_cores"] == 0.4
        assert row["edge_cgroup_cores"] == 2.5
        assert row["workload_cores"] == 0.25
        assert row["other_cores"] == 0.0  # 1.6 - 2.5 - 0.25 clamps: jiffies and cgroups are not read at one instant
        assert row["max_cpu_busy_pct"] == 80.0
        assert row["generator_busy_pct"] == 20.0

    def test_a_restarted_edge_is_marked_not_read_as_negative_rates(self) -> None:
        a = tl.parse_edge(EDGE_METRICS)
        b = {**a, "process_cpu_seconds_total": 1.0, "go_gc_duration_seconds_count": 3}
        row = tl.interval(self._sample(0.0, a, None), self._sample(2.0, b, None), 0.0)
        assert row["edge_reset"] is True
        assert "traefik_cores" not in row and "gc_per_s" not in row

    def test_a_missed_read_leaves_its_fields_out(self) -> None:
        row = tl.interval(self._sample(0.0, None, None), self._sample(2.0, None, None), 0.0)
        assert row == {"t": 2.0}


class TestSampler:
    def test_it_samples_for_the_step_and_survives_a_failed_read(self) -> None:
        now = [0.0]
        reads = iter([EDGE_METRICS, subprocess.CalledProcessError(1, "kubectl"), EDGE_METRICS, EDGE_METRICS])

        def edge() -> dict:
            got = next(reads)
            if isinstance(got, Exception):
                raise got
            return tl.parse_edge(got)

        readers = tl.Readers(edge=edge, node=lambda: None, generator=lambda: None)

        def sleep(seconds: float) -> None:
            now[0] += seconds

        rows = tl.sample_timeline(readers, seconds=6, every=2, clock=lambda: now[0], sleep=sleep)
        assert [r["t"] for r in rows] == [2.0, 4.0, 6.0]
        assert "edge_rps" not in rows[0]  # the second read failed, so neither interval touching it has a rate
        assert rows[2]["edge_rps"] == 0

    def test_zero_seconds_between_samples_is_refused(self) -> None:
        with pytest.raises(ValueError):
            tl.sample_timeline(tl.Readers(lambda: None, lambda: None, lambda: None), seconds=6, every=0)


class TestNodeCommand:
    def test_it_reads_both_cgroups_and_tolerates_one_that_is_gone(self) -> None:
        cmd = tl.node_command("0fc274d4-eab5", "1a2b")
        assert "pod0fc274d4_eab5.slice/cpu.stat" in cmd and "pod1a2b.slice/cpu.stat" in cmd
        assert cmd.count("2>/dev/null") == 3

    @pytest.mark.parametrize("uid", ["a b", "x;rm", "../etc", ""])
    def test_a_uid_that_is_not_a_uid_is_refused(self, uid: str) -> None:
        with pytest.raises(ValueError):
            tl.node_command(uid, "1a2b")


def _pod(name: str, uid: str, ports: list[dict] | None = None) -> dict:
    container = {"name": "c", "ports": ports or []}
    return {"metadata": {"name": name, "uid": uid}, "spec": {"containers": [container]}}


class TestLabReaders:
    """What the run reads each sample: Traefik through the apiserver, the node and k6's host over ssh."""

    def _lab(self, calls: list) -> lt.Lab:
        lab = lt.Lab(REPO, "kc", "op", "node", "gen")
        pods = {
            "traefik": _pod(
                "traefik-abc",
                "0fc2-eab5",
                [{"name": "web", "containerPort": 8000}, {"name": "metrics", "containerPort": 9100}],
            ),
            "api": _pod("api-xyz", "1a2b"),
        }
        lab.pod = lambda workload, namespace="kubelab": pods[workload]  # type: ignore[method-assign]
        lab.kubectl = lambda *a, **k: calls.append(("kubectl", a, k)) or EDGE_METRICS  # type: ignore[method-assign]
        lab.ssh = lambda node, cmd, stdin=None, timeout=60: (
            calls.append(("ssh", node, cmd, timeout))
            or (  # type: ignore[method-assign]
                "cpu 1 0 0 9 0 0 0" if node == "gen" else _node(100, 300, 20, 1, 2)
            )
        )
        return lab

    def test_edge_is_read_from_the_named_metrics_port_without_impersonation(self) -> None:
        calls: list = []
        readers = self._lab(calls).timeline_readers("api")
        assert readers.edge()["traefik_open_connections"] == 40
        ((_, args, kwargs),) = calls
        assert args[:3] == ("get", "--raw", "/api/v1/namespaces/kube-system/pods/traefik-abc:9100/proxy/metrics")
        assert not kwargs.get("impersonate")

    def test_node_and_generator_are_one_bounded_ssh_each(self) -> None:
        calls: list = []
        readers = self._lab(calls).timeline_readers("api")
        assert readers.node()["conntrack"] == 400
        assert readers.generator() == [1, 0, 0, 9, 0, 0, 0]
        (_, node, cmd, timeout), (_, gen, _, gen_timeout) = calls
        assert (node, gen) == ("node", "gen")
        assert "pod0fc2_eab5.slice" in cmd and "pod1a2b.slice" in cmd
        assert max(timeout, gen_timeout) <= tl.SAMPLE_SECONDS * 5  # a hung read must not outlive the step

    def test_an_edge_without_a_metrics_port_is_refused(self) -> None:
        lab = self._lab([])
        lab.pod = lambda workload, namespace="kubelab": _pod("t", "ab")  # type: ignore[method-assign]
        with pytest.raises(lt.LoadTestRefused):
            lab.timeline_readers("api")


class TestStepCarriesItsTimeline:
    def _fake(self, monkeypatch: pytest.MonkeyPatch, seen: list) -> lt.Lab:
        lab = lt.Lab(REPO, "kc", "op", "node", "gen")
        monkeypatch.setattr(lab, "cpu_line", lambda _n: "cpu 1 0 0 9 0 0 0")
        monkeypatch.setattr(lab, "cpu_stat", lambda _w: "throttled_usec 0")
        monkeypatch.setattr(lab, "pod", lambda *_a, **_k: {"metadata": {"uid": "u"}})
        monkeypatch.setattr(lab, "edge_state", lambda: ("a", 0))
        monkeypatch.setattr(lab, "ssh", lambda *_a, **_k: "")
        monkeypatch.setattr(lab, "timeline_readers", lambda w: seen.append(("readers", w)) or "readers")
        monkeypatch.setattr(lt, "_sample_mid_step", lambda *_a: ({}, 0))
        monkeypatch.setattr(lt, "parse_summary", lambda _s: {})
        monkeypatch.setattr(lt, "classify", lambda *_a: [])
        monkeypatch.setattr(
            tl, "sample_timeline", lambda r, seconds, every: seen.append((r, seconds, every)) or [{"t": every}]
        )
        return lab

    def _step(self, lab: lt.Lab, sample_seconds: int) -> dict:
        target = lt.Target("api", "api.example", "/health", "api")
        return lt.run_step(lab, "img", "", target, "1.2.3.4", 100, 60, bypass=None, sample_seconds=sample_seconds)

    def test_a_sampled_step_covers_k6s_start_and_end(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list = []
        step = self._step(self._fake(monkeypatch, seen), 2)
        assert step["timeline"] == [{"t": 2}]
        assert ("readers", 60 + lt.TIMELINE_TAIL_SECONDS, 2) in seen

    def test_zero_turns_it_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        seen: list = []
        step = self._step(self._fake(monkeypatch, seen), 0)
        assert "timeline" not in step and seen == []


class TestRunPassesTheInterval:
    def _run(self, monkeypatch: pytest.MonkeyPatch, sample_seconds: int) -> tuple[dict, list]:
        from tests.test_load_test import _DyingLab, _step

        got: list = []
        monkeypatch.setattr(
            lt,
            "run_step",
            lambda *_a, sample_seconds, **_k: got.append(sample_seconds) or {**_step(), "reasons": ["errors"]},
        )
        monkeypatch.setattr(lt, "_runtime_facts", lambda *_: {})
        monkeypatch.setattr(lt, "wait_for_stable_edge", lambda *_: None)
        monkeypatch.setattr("time.sleep", lambda _: None)
        target = lt.Target("api", "api.example", "/health", "api")
        return lt.run(_DyingLab(), "img", (target,), "1.2.3.4", 1, 1, 50, sample_seconds=sample_seconds), got

    def test_every_step_baseline_included_is_sampled_and_the_result_says_how_often(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        result, got = self._run(monkeypatch, 2)
        assert got and set(got) == {2}
        assert result["facts"]["sample_seconds"] == 2

    def test_a_negative_interval_is_refused(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(lt.LoadTestRefused):
            self._run(monkeypatch, -1)


def test_iowait_is_idle_not_busy() -> None:
    """A CPU waiting on disk is free to run Traefik, so it must not read as load."""
    a = {"t": 0.0, "edge": None, "node": None, "generator": [10, 0, 0, 90, 0]}
    b = {"t": 2.0, "edge": None, "node": None, "generator": [30, 0, 0, 150, 20]}
    assert tl.interval(a, b, 0.0)["generator_busy_pct"] == 20.0


class TestWhatTheShellReallyWrites:
    """`echo @@` after an empty `cat` leaves two marker lines back to back, with no blank line
    between them; the fixture builder above adds one, so these use the literal bytes."""

    STAT = "cpu  1 0 0 9 0 0 0\ncpu0 1 0 0 9 0 0 0\n"

    def test_a_gone_edge_cgroup_loses_only_that_cgroup(self) -> None:
        node = tl.parse_node(f"{self.STAT}@@\n400\n@@\n@@\nusage_usec 7\nnr_throttled 0\n")
        assert (node["conntrack"], node["edge_usec"], node["workload_usec"]) == (400, None, 7)

    def test_both_cgroups_and_conntrack_gone_still_reads_the_cpus(self) -> None:
        node = tl.parse_node(f"{self.STAT}@@\n@@\n@@\n")
        assert set(node["cpus"]) == {"cpu", "cpu0"}
        assert (node["conntrack"], node["edge_usec"], node["workload_usec"]) == (None, None, None)

    def test_every_read_but_proc_stat_tolerates_a_missing_file(self) -> None:
        assert tl.node_command("ab", "cd").count("2>/dev/null") == 3


def test_the_edge_read_is_bounded_by_the_apiserver_too() -> None:
    calls: list = []
    lab = TestLabReaders()._lab(calls)
    lab.timeline_readers("api").edge()
    ((_, args, _),) = calls
    assert f"--request-timeout={lt.TIMELINE_READ_TIMEOUT}s" in args
