"""How long `ci.yml / Tests` keeps a pull request waiting, measured from the runs themselves.

AC2 of #3078 asks for a `Tests` p50 of 10 min or less over 20 pull request runs.
Since #3111, `Tests` is the end of a chain: three `Tests shard N` jobs run the
suite, then `Tests` combines their coverage. The time a PR waits is therefore
measured from the first shard's start to the completion of `Tests`.

That number mixes two things that do not have the same owner: the test suite, and
waiting for a hosted runner. The columns are views of it, not a partition, and
must not be summed. Exactly, `wall` = (last shard end - first shard start) + `wait`
+ `aggregate`. The first term is the shard phase, and two columns look into it:
`shard_max`, the slowest shard's own duration (the suite), and `skew`, how far
apart the shards started (runner wait inside that phase). They overlap. `wait` is
`Tests` not starting when the last shard finished, and `aggregate` is `Tests`'
own run time. On 2026-11-06, with five unattended runs open at once, the
shards still ran in about 7 min while the wall time tripled. So every sample keeps
the parts apart, and the report shows the first, last and whole windows, because
a single window chosen after the fact is a number that can be shopped for.

Only runs whose `Tests` job succeeded are samples. A failed `Tests` stops early
and would pull the median down for the wrong reason. That filter has a bias of its
own: a run that the concurrency group cancels while it is still queued is dropped
too, and those runs cluster in exactly the saturated windows, so a saturated
window's p50 reads lower than what PRs lived through. The report counts what it
dropped so that bias stays visible. A rerun (`run_attempt > 1`) is dropped as
well: its jobs endpoint mixes the attempts, so its timings span both.

`wall` starts at the first shard's start, as AC2 defines it. `queue`, from the
run's creation to that start, is reported beside it and is not part of it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
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
    queue: float = 0.0
    aggregate: float = 0.0


@dataclass(frozen=True)
class Collected:
    samples: list[Sample]
    dropped: int
    # One entry per run in chronological order: True when it became a sample.
    # It places every dropped run between two samples, so a window can count
    # the drops that fell inside it.
    kept: tuple[bool, ...] = ()


@dataclass(frozen=True)
class Window:
    label: str
    count: int
    p50_wall: float
    p50_shard_max: float
    p50_wait: float
    p50_skew: float
    p50_queue: float
    p50_aggregate: float
    dropped: int = 0


def _ts(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def sample(jobs: Sequence[dict[str, Any]], run_id: int = 0, created_at: str | None = None) -> Sample | None:
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
        queue=max(min(starts) - _ts(created_at), 0.0) if created_at else 0.0,
        aggregate=agg_end - agg_start,
    )


def median(values: Iterable[float]) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("the median of no samples is undefined")
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2


def normalise_since(since: str) -> str:
    """`since` as a UTC `...Z` instant, so no `+` offset reaches the query string."""
    parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"--since {since!r} has no timezone; give a UTC instant such as 2026-11-05T08:13:42Z")
    return parsed.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def collect(api: Api, repo: str, workflow: str, since: str) -> Collected:
    """Every completed pull request run of `workflow` created at or after `since`, oldest first.

    REST, not GraphQL: separate rate-limit buckets, and GraphQL is the one the
    fleet exhausts (#1651).
    """
    since = normalise_since(since)
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
    kept = []
    for run in reversed(runs):
        got = None
        if run.get("run_attempt", 1) == 1:
            jobs = api.json(f"repos/{repo}/actions/runs/{run['id']}/jobs?per_page=100")["jobs"]
            got = sample(jobs, run_id=run["id"], created_at=run.get("created_at"))
        kept.append(got is not None)
        if got is not None:
            samples.append(got)
    return Collected(samples=samples, dropped=len(runs) - len(samples), kept=tuple(kept))


def dropped_within(kept: Sequence[bool], first: int, last: int) -> int:
    """Runs dropped between sample `first` and sample `last` (0-based, inclusive).

    A window that holds the first sample also owns the drops before it, and one
    that holds the last sample owns the drops after it, so the whole span's row
    accounts for every dropped run.
    """
    final = sum(kept) - 1
    seen, inside = -1, 0
    for k in kept:
        if k:
            seen += 1
        elif first <= seen < last or (seen == -1 and first == 0) or (seen == final and last == final):
            inside += 1
    return inside


def _window(label: str, samples: Sequence[Sample]) -> Window:
    return Window(
        label=label,
        count=len(samples),
        p50_wall=median(s.wall for s in samples),
        p50_shard_max=median(s.shard_max for s in samples),
        p50_wait=median(s.wait for s in samples),
        p50_skew=median(s.skew for s in samples),
        p50_queue=median(s.queue for s in samples),
        p50_aggregate=median(s.aggregate for s in samples),
    )


def report(samples: Sequence[Sample], window: int = 20, kept: Sequence[bool] = ()) -> list[Window]:
    """The first `window`, the last `window` and all samples, each with its medians
    and the runs dropped between its first and last sample."""
    if not samples:
        raise ValueError("no samples to report")
    n = len(samples)
    spans = [
        (f"first {window}", 0, min(window, n) - 1),
        (f"last {window}", max(n - window, 0), n - 1),
        ("all", 0, n - 1),
    ]
    return [replace(_window(label, samples[a : b + 1]), dropped=dropped_within(kept, a, b)) for label, a, b in spans]
