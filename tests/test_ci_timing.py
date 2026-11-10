"""`toolkit tools tests-p50`: AC2 of #3078 measured by a command, not a pasted pipeline."""

from __future__ import annotations

import subprocess
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
    assert sample.aggregate == 90  # the Tests job's own run time
    assert sample.queue == 0.0  # no creation time given


def test_queue_is_creation_to_first_shard_start_and_stays_outside_wall() -> None:
    sample = ci_timing.sample(_run_jobs(), created_at="2026-11-06T09:56:00Z")
    assert sample is not None
    assert sample.queue == 4 * 60
    assert sample.wall == 11 * 60 + 30


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

    assert [s.run_id for s in got.samples] == [1, 3]
    assert got.dropped == 1
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


def test_a_rerun_is_dropped_because_its_jobs_mix_attempts() -> None:
    runs = [{"id": 2, "run_attempt": 2}, {"id": 1, "run_attempt": 1}]
    api = FakeApi(runs, {1: _run_jobs(), 2: _run_jobs()})

    got = ci_timing.collect(api, "o/r", "ci.yml", "2026-11-05T08:13:42Z")

    assert [s.run_id for s in got.samples] == [1]
    assert got.dropped == 1
    assert not any("/runs/2/jobs" in p for p in api.paths)


@pytest.mark.parametrize(
    ("given", "expected"),
    [("2026-11-05T08:13:42Z", "2026-11-05T08:13:42Z"), ("2026-11-05T01:13:42-07:00", "2026-11-05T08:13:42Z")],
)
def test_since_is_normalised_to_a_utc_instant(given: str, expected: str) -> None:
    assert ci_timing.normalise_since(given) == expected


def test_a_since_without_a_timezone_is_refused() -> None:
    with pytest.raises(ValueError):
        ci_timing.normalise_since("2026-11-05T08:13:42")


def _samples(walls_min: list[float]) -> ci_timing.Collected:
    return ci_timing.Collected(
        samples=[
            ci_timing.Sample(run_id=i, wall=w * 60, shard_max=420, wait=0, skew=0) for i, w in enumerate(walls_min)
        ],
        dropped=0,
    )


@pytest.mark.parametrize(
    ("walls", "code"),
    [([8.0] * 20, 0), ([12.0] * 20, 1), ([8.0] * 19, 2), ([20.0] * 20 + [8.0] * 20, 0), ([8.0] * 20 + [20.0] * 20, 1)],
    ids=["within", "over", "under-sampled", "only-the-last-window-gates", "a-slow-last-window-fails"],
)
def test_the_command_exit_status(monkeypatch: pytest.MonkeyPatch, walls: list[float], code: int) -> None:
    from typer.testing import CliRunner

    from toolkit.cli.tools import app

    monkeypatch.setattr(ci_timing, "collect", lambda *a, **k: _samples(walls))
    result = CliRunner().invoke(app, ["tests-p50", "--since", "2026-11-05T08:13:42Z"])
    assert result.exit_code == code


@pytest.mark.parametrize(
    "error",
    [RuntimeError("gh api failed"), FileNotFoundError("gh"), subprocess.TimeoutExpired("gh", 60)],
    ids=["api-error", "no-gh", "timeout"],
)
def test_the_command_exits_2_when_the_runs_cannot_be_read(monkeypatch: pytest.MonkeyPatch, error: Exception) -> None:
    from typer.testing import CliRunner

    from toolkit.cli.tools import app

    def boom(*a: object, **k: object) -> ci_timing.Collected:
        raise error

    monkeypatch.setattr(ci_timing, "collect", boom)
    result = CliRunner().invoke(app, ["tests-p50", "--since", "2026-11-05T08:13:42Z"])
    assert result.exit_code == 2


def test_wall_is_the_shard_phase_plus_wait_plus_aggregate_and_skew_overlaps_it() -> None:
    s = ci_timing.sample(_run_jobs())
    assert s is not None
    shard_phase = 7 * 60  # 10:00:00 -> 10:07:00
    assert s.wall == shard_phase + s.wait + s.aggregate
    assert s.shard_max + s.skew + s.wait + s.aggregate != s.wall  # columns are views, not a partition


def test_dropped_runs_are_counted_inside_the_window_they_fell_in() -> None:
    # runs in time order: S D S D D S S D
    kept = [True, False, True, False, False, True, True, False]
    assert ci_timing.dropped_within(kept, 0, 1) == 1  # first two samples
    assert ci_timing.dropped_within(kept, 1, 2) == 2  # between sample 1 and sample 2
    assert ci_timing.dropped_within(kept, 2, 3) == 1  # the last window owns the trailing drop
    assert ci_timing.dropped_within(kept, 0, 3) == kept.count(False)  # the whole span owns every drop
    assert ci_timing.dropped_within([False, True, True], 0, 0) == 1  # the first window owns a leading drop


def test_the_report_carries_each_windows_drops() -> None:
    samples = [ci_timing.Sample(run_id=i, wall=60, shard_max=60, wait=0, skew=0) for i in range(4)]
    kept = [True, False, False, True, True, True]
    first, last, whole = ci_timing.report(samples, window=2, kept=kept)
    assert (first.dropped, last.dropped, whole.dropped) == (2, 0, 2)
