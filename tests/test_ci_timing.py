"""`toolkit tools tests-p50`: AC2 of #3078 measured by a command, not a pasted pipeline."""

from __future__ import annotations

from typing import Any

import pytest

from toolkit.features import ci_timing


def _job(name: str, start: str, end: str, conclusion: str = "success") -> dict[str, Any]:
    return {
        "name": name,
        "started_at": f"2026-11-06T{start}Z",
        "completed_at": f"2026-11-06T{end}Z",
        "conclusion": conclusion,
    }


def _run_jobs(tests_conclusion: str = "success") -> list[dict[str, Any]]:
    return [
        _job("Validate", "10:00:00", "10:00:10"),
        _job("Tests shard 1", "10:00:00", "10:07:00"),
        _job("Tests shard 2", "10:02:00", "10:06:00"),
        _job("Tests shard 3", "10:01:00", "10:05:00"),
        _job("Tests", "10:10:00", "10:11:30", tests_conclusion),
    ]


def test_a_sample_splits_wall_time_into_shard_wait_and_skew() -> None:
    sample = ci_timing.sample(_run_jobs())
    assert sample is not None
    assert sample.wall == 11 * 60 + 30  # first shard start -> Tests completion
    assert sample.shard_max == 7 * 60  # slowest shard's own duration
    assert sample.wait == 3 * 60  # last shard done -> Tests started
    assert sample.skew == 2 * 60  # first shard start -> last shard start


@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "skipped", None])
def test_a_run_whose_tests_job_did_not_pass_is_not_a_timing_sample(conclusion: str | None) -> None:
    assert ci_timing.sample(_run_jobs(conclusion)) is None  # type: ignore[arg-type]


def test_a_run_without_shards_is_not_a_sample() -> None:
    assert ci_timing.sample([_job("Tests", "10:00:00", "10:20:00")]) is None


def test_the_median_of_an_even_count_is_the_mean_of_the_middle_pair() -> None:
    assert ci_timing.median([4, 1, 3, 2]) == 2.5
    assert ci_timing.median([5, 1, 3]) == 3


def test_the_median_of_nothing_is_refused() -> None:
    with pytest.raises(ValueError):
        ci_timing.median([])


class FakeApi:
    def __init__(self, runs: list[dict[str, Any]], jobs: dict[int, list[dict[str, Any]]]) -> None:
        self.runs = runs
        self.jobs = jobs
        self.paths: list[str] = []

    def json(self, path: str) -> Any:
        self.paths.append(path)
        if "/jobs" in path:
            run_id = int(path.split("/runs/")[1].split("/")[0])
            return {"jobs": self.jobs[run_id]}
        page = int(path.split("&page=")[1].split("&")[0])
        return {"workflow_runs": self.runs if page == 1 else []}

    def raw(self, path: str) -> str:  # pragma: no cover - unused
        raise NotImplementedError


def test_samples_are_returned_oldest_first_and_skip_failed_runs() -> None:
    runs = [{"id": 3}, {"id": 2}, {"id": 1}]  # the API answers newest first
    jobs = {3: _run_jobs(), 2: _run_jobs("failure"), 1: _run_jobs()}
    api = FakeApi(runs, jobs)

    got = ci_timing.collect(api, "o/r", "ci.yml", "2026-11-05T08:13:42Z")

    assert [s.run_id for s in got] == [1, 3]
    listing = api.paths[0]
    assert "event=pull_request" in listing
    assert "status=completed" in listing
    assert "created=%3E%3D2026-11-05T08:13:42Z" in listing


def test_the_report_names_the_first_last_and_whole_windows() -> None:
    samples = [
        ci_timing.Sample(run_id=i, wall=w * 60, shard_max=420, wait=0, skew=0) for i, w in enumerate(range(1, 31))
    ]

    report = ci_timing.report(samples, window=20)

    assert [(r.label, r.count) for r in report] == [("first 20", 20), ("last 20", 20), ("all", 30)]
    assert report[0].p50_wall == 10.5 * 60
    assert report[1].p50_wall == 20.5 * 60
    assert report[2].p50_wall == 15.5 * 60
