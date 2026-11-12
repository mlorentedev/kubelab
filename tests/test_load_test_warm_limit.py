"""Separating what limits warm capacity at the knee (#3308).

The warm-degraded steps all held k6's whole pool (3,200 to 4,000 connections, left
by the burst) and one busy CPU. A cap on the pool separates the connection count
from the rate; the busiest CPU's own softirq separates a network queue from work.
"""

from __future__ import annotations

import pathlib

import pytest

from toolkit.features import load_test as lt
from toolkit.features import load_test_timeline as tl

REPO = pathlib.Path(__file__).resolve().parents[1]
SCRIPT = (REPO / "infra/load-test/constant-rate.js").read_text(encoding="utf-8")
TARGET = lt.Target(name="api-health", host="api.staging.kubelab.live", path="/health", workload="api")


def _stat(*cpus: tuple[int, int, int]) -> str:
    """(busy user, idle, softirq) per CPU; the aggregate line is their sum."""
    lines = [f"cpu{i} {u} 0 0 {idle} 0 0 {s} 0 0 0" for i, (u, idle, s) in enumerate(cpus)]
    total = [sum(c[k] for c in cpus) for k in range(3)]
    stat = "\n".join([f"cpu  {total[0]} 0 0 {total[1]} 0 0 {total[2]} 0 0 0", *lines, "intr 1"])
    return tl.SEPARATOR.join([stat, "400", "usage_usec 1", "usage_usec 1"])


class TestTheBusiestCpu:
    def _row(self) -> dict:
        a = tl.parse_node(_stat((0, 0, 0), (0, 0, 0)))
        # cpu0: 50 user + 40 softirq of 100; cpu1: 20 user of 100.
        b = tl.parse_node(_stat((50, 10, 40), (20, 80, 0)))
        return tl._node_row(a, b)

    def test_it_is_named(self) -> None:
        assert self._row()["max_cpu"] == "cpu0"

    def test_its_softirq_is_read_on_that_cpu_alone(self) -> None:
        row = self._row()
        assert row["max_cpu_busy_pct"] == 90.0
        assert row["max_cpu_softirq_pct"] == 40.0


class TestThePoolCap:
    def test_the_script_takes_a_cap(self) -> None:
        assert "LT_MAX_VUS" in SCRIPT
        assert "maxVUs: maxVUs" in SCRIPT or "maxVUs," in SCRIPT

    def test_the_pre_allocated_users_never_exceed_the_cap(self) -> None:
        assert "Math.min(" in SCRIPT.split("preAllocatedVUs")[1].split("\n")[0]

    def test_it_reaches_k6_only_when_asked(self) -> None:
        assert "LT_MAX_VUS" not in lt.k6_env(TARGET, "10.0.0.1", 100, 60, None)
        assert lt.k6_env(TARGET, "10.0.0.1", 100, 60, None, max_vus=800)["LT_MAX_VUS"] == "800"

    @pytest.mark.parametrize("bad", [0, -1])
    def test_a_cap_below_one_is_refused(self, bad: int) -> None:
        with pytest.raises(lt.LoadTestRefused):
            lt.k6_env(TARGET, "10.0.0.1", 100, 60, None, max_vus=bad)

    def test_the_command_and_make_pass_it(self) -> None:
        cli = (REPO / "toolkit/cli/infra.py").read_text(encoding="utf-8")
        assert "--max-vus" in cli and "max_vus=max_vus" in cli
        make = (REPO / "Makefile").read_text(encoding="utf-8")
        assert "$(if $(MAX_VUS),--max-vus $(MAX_VUS))" in make

    def test_the_result_records_it(self) -> None:
        source = (REPO / "toolkit/features/load_test.py").read_text(encoding="utf-8")
        assert '"max_vus": max_vus' in source
