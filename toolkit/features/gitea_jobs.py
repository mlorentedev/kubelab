"""Describe a Gitea Actions run from its jobs: which ran, on which runner, and which no runner took (#1637, #3079).

A run's own duration mixes waiting with running. openkm-brain's run 810 lasted 1,674.8
min and was recorded as a job that hung while holding a runner slot. Its jobs show
three `windows-latest` jobs that no runner ever took (`runner_id` 0, `started_at`
unset), cancelled by the abandoned-job bound 27.9 h later. A waiting job holds no
slot, and the bounds that stop a running job never apply to it. Only the job fields
tell the two apart, so this reads them and nothing else.

Gitea reports an unset `started_at` as the Unix epoch (1.27.3, measured) and older
versions as `0001-01-01`. Both are read as "never".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

#: Any timestamp before this is a zero value, not a time something happened.
_UNSET_BEFORE = datetime.fromisoformat("1971-01-01T00:00:00+00:00")


def _ts(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed >= _UNSET_BEFORE else None


def _minutes(start: datetime, end: datetime) -> float:
    return round((end - start).total_seconds() / 60, 1)


@dataclass(frozen=True)
class Job:
    id: int
    name: str
    status: str
    conclusion: Optional[str]
    #: True once a runner took the job (its start is set).
    taken: bool
    #: Not taken and not finished: still waiting for a runner. It may start any second,
    #: so it is not evidence that no runner will take it.
    waiting: bool
    #: Never meant to run: `needs:` failed upstream or `if:` was false. Not a missing runner.
    skipped: bool
    runner: Optional[str]
    #: Minutes from start to completion, or to `now` while it runs. None if never started.
    ran_minutes: Optional[float]


@dataclass(frozen=True)
class RunSummary:
    id: int
    status: str
    conclusion: Optional[str]
    minutes: Optional[float]
    jobs: int
    #: Finished without any runner taking it (run 810's case).
    never_started: int
    #: Not taken yet, run still live.
    waiting: int
    #: Skipped by the workflow itself; excluded from `never_started`.
    skipped: int
    longest_ran_minutes: Optional[float]


def describe_job(job: Mapping[str, Any], now: datetime) -> Job:
    started = _ts(job.get("started_at"))
    taken = started is not None
    ran = None
    if started is not None:
        ran = _minutes(started, _ts(job.get("completed_at")) or now)
    return Job(
        id=int(job["id"]),
        name=str(job.get("name", "")),
        status=str(job.get("status", "")),
        conclusion=job.get("conclusion") or None,
        taken=taken,
        waiting=not taken and job.get("status") != "completed",
        skipped=not taken and job.get("conclusion") == "skipped",
        runner=job.get("runner_name") if taken else None,
        ran_minutes=ran,
    )


def summarize_run(run: Mapping[str, Any], jobs: Sequence[Mapping[str, Any]], now: datetime) -> RunSummary:
    described = [describe_job(job, now) for job in jobs]
    started = _ts(run.get("started_at"))
    minutes = _minutes(started, _ts(run.get("completed_at")) or now) if started else None
    ran = [job.ran_minutes for job in described if job.ran_minutes is not None]
    return RunSummary(
        id=int(run["id"]),
        status=str(run.get("status", "")),
        conclusion=run.get("conclusion") or None,
        minutes=minutes,
        jobs=len(described),
        never_started=sum(1 for job in described if not (job.taken or job.waiting or job.skipped)),
        waiting=sum(1 for job in described if job.waiting),
        skipped=sum(1 for job in described if job.skipped),
        longest_ran_minutes=max(ran) if ran else None,
    )
