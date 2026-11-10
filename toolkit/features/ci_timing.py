"""How long `ci.yml / Tests` keeps a pull request waiting, measured from the runs themselves.

AC2 of #3078 asks for a `Tests` p50 of 10 min or less over 20 pull request runs.
Since #3111, `Tests` is the end of a chain: three `Tests shard N` jobs run the
suite, then `Tests` combines their coverage. The time a PR waits is therefore
measured from the first shard's start to the completion of `Tests`.

That number mixes two things that do not have the same owner. The slowest shard's
own duration is the test suite. The rest is waiting for a hosted runner: the
shards not starting together (`skew`) and `Tests` not starting when the last shard
finished (`wait`). On 2026-11-06, with five unattended runs open at once, the
shards still ran in about 7 min while the wall time tripled. So every sample keeps
the parts apart, and the report shows the first, last and whole windows, because
a single window chosen after the fact is a number that can be shopped for.

Only runs whose `Tests` job succeeded are samples. A failed or cancelled `Tests`
stops early and would pull the median down for the wrong reason.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from toolkit.features.deploy_shape import Api

SHARD_PREFIX = "Tests shard"
AGGREGATE = "Tests"


@dataclass(frozen=True)
class Sample:
    run_id: int
    wall: float
    shard_max: float
    wait: float
    skew: float


@dataclass(frozen=True)
class Window:
    label: str
    count: int
    p50_wall: float
    p50_shard_max: float
    p50_wait: float
    p50_skew: float


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def sample(jobs: Sequence[dict[str, Any]], run_id: int = 0) -> Sample | None:
    """One run's timing, or None when the run is not a timing sample."""
    shards = [j for j in jobs if j.get("name", "").startswith(SHARD_PREFIX)]
    aggregate = next((j for j in jobs if j.get("name") == AGGREGATE), None)
    if not shards or aggregate is None or aggregate.get("conclusion") != "success":
        return None
    starts = [_ts(j["started_at"]) for j in shards]
    ends = [_ts(j["completed_at"]) for j in shards]
    agg_start, agg_end = _ts(aggregate["started_at"]), _ts(aggregate["completed_at"])
    return Sample(
        run_id=run_id,
        wall=agg_end - min(starts),
        shard_max=max(e - s for s, e in zip(starts, ends, strict=True)),
        wait=max(agg_start - max(ends), 0.0),
        skew=max(starts) - min(starts),
    )


def median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("the median of no samples is undefined")
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def collect(api: Api, repo: str, workflow: str, since: str) -> list[Sample]:
    """Every completed pull request run of `workflow` created at or after `since`, oldest first.

    REST, not GraphQL: separate rate-limit buckets, and GraphQL is the one the
    fleet exhausts (#1651).
    """
    runs: list[dict[str, Any]] = []
    page = 1
    while True:
        batch = api.json(
            f"repos/{repo}/actions/workflows/{workflow}/runs"
            f"?event=pull_request&status=completed&created=%3E%3D{since}&per_page=100&page={page}"
        )["workflow_runs"]
        if not batch:
            break
        runs.extend(batch)
        page += 1
    samples = []
    for run in reversed(runs):
        jobs = api.json(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
        got = sample(jobs, run_id=run["id"])
        if got is not None:
            samples.append(got)
    return samples


def _window(label: str, samples: Sequence[Sample]) -> Window:
    return Window(
        label=label,
        count=len(samples),
        p50_wall=median(s.wall for s in samples),
        p50_shard_max=median(s.shard_max for s in samples),
        p50_wait=median(s.wait for s in samples),
        p50_skew=median(s.skew for s in samples),
    )


def report(samples: Sequence[Sample], window: int = 20) -> list[Window]:
    """The first `window`, the last `window` and all samples, each with its medians."""
    if not samples:
        raise ValueError("no samples to report")
    return [
        _window(f"first {window}", samples[:window]),
        _window(f"last {window}", samples[-window:]),
        _window("all", samples),
    ]
