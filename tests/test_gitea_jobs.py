"""Reading a Gitea Actions run's jobs, and telling a job that waited from one that ran (#1637, #3079).

The case this exists for, measured on prod 2026-11-14: openkm-brain's run 810 lasted
1,674.8 min, and the issue recorded it as a job that "hung while holding a slot". Its
jobs said otherwise: three `windows-latest` jobs had `runner_id` 0 and a `started_at`
of 1970-01-01, so no runner ever took them, and the abandoned-job bound cancelled them
27.9 h later. A run's duration cannot tell those two apart. A job's fields can.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from typer.testing import CliRunner

from toolkit.cli import services
from toolkit.features.gitea_client import PAGE_SIZE, GiteaClient, GiteaError
from toolkit.features.gitea_jobs import describe_job, summarize_run

NOW = datetime(2026, 11, 14, 12, 0, tzinfo=timezone.utc)


def _job(**fields: Any) -> dict[str, Any]:
    base = {
        "id": 1,
        "name": "job",
        "status": "completed",
        "conclusion": "success",
        "started_at": "2026-10-09T02:20:39Z",
        "completed_at": "2026-10-09T02:24:36Z",
        "runner_id": 1,
        "runner_name": "kubelab-bee-gitea",
    }
    return {**base, **fields}


# The never-started job, as Gitea 1.27.3 answered for run 810's windows-latest jobs.
NEVER_TAKEN = _job(
    id=2520,
    name="Dependency audit (windows-latest, Python 3.11)",
    conclusion="cancelled",
    started_at="1970-01-01T00:00:00Z",
    completed_at="2026-10-10T06:15:29Z",
    runner_id=0,
    runner_name=None,
)


def test_a_job_no_runner_took_is_reported_as_never_started() -> None:
    job = describe_job(NEVER_TAKEN, NOW)

    assert job.taken is False
    assert job.ran_minutes is None, "a job that never started has no running time, not 0 and not 1970's"


def test_a_job_a_runner_took_reports_its_runner_and_running_time() -> None:
    job = describe_job(_job(), NOW)

    assert job.taken is True
    assert job.runner == "kubelab-bee-gitea"
    assert job.ran_minutes == 4.0


def test_a_job_still_running_is_measured_up_to_now() -> None:
    running = _job(status="in_progress", conclusion=None, completed_at=None, started_at="2026-11-14T09:00:00Z")
    job = describe_job(running, NOW)

    assert job.taken is True
    assert job.ran_minutes == 180.0


def test_a_waiting_job_with_no_runner_is_not_taken_even_before_its_epoch_start() -> None:
    """Gitea reports `0001-01-01` on some versions where 1.27 reports 1970: both mean unset."""
    waiting = _job(status="waiting", conclusion=None, started_at="0001-01-01T00:00:00Z", completed_at=None, runner_id=0)
    job = describe_job({**waiting, "runner_name": None}, NOW)

    assert job.taken is False
    assert job.waiting is True, "a live job no runner took yet is waiting, not never started"


def test_a_finished_job_no_runner_took_is_not_waiting() -> None:
    assert describe_job(NEVER_TAKEN, NOW).waiting is False


def test_run_810_reads_as_three_jobs_that_waited_not_one_that_hung() -> None:
    run = {
        "id": 810,
        "status": "completed",
        "conclusion": "cancelled",
        "started_at": "2026-10-09T02:20:39Z",
        "completed_at": "2026-10-10T06:15:29Z",
    }
    jobs = [_job(id=2517), _job(id=2523), NEVER_TAKEN, {**NEVER_TAKEN, "id": 2521}, {**NEVER_TAKEN, "id": 2522}]

    summary = summarize_run(run, jobs, NOW)

    assert summary.minutes == 1674.8
    assert summary.never_started == 3
    assert summary.waiting == 0
    assert summary.longest_ran_minutes == 4.0


class RecordingClient(GiteaClient):
    def __init__(self, pages: list[Any]) -> None:
        super().__init__("https://forge.invalid", token="unused")
        self.pages = pages
        self.requested: list[str] = []

    def _request(self, method: str, endpoint: str, **kwargs: Any) -> Any:
        self.requested.append(endpoint)
        return self.pages.pop(0) if self.pages else {}


def test_a_run_s_jobs_are_read_from_every_page() -> None:
    full = {"jobs": [_job(id=n) for n in range(PAGE_SIZE)]}
    client = RecordingClient([full, {"jobs": [_job(id=999)]}])

    jobs = client.list_run_jobs("teledyne", "openkm-brain", 810)

    assert len(jobs) == PAGE_SIZE + 1
    assert client.requested[0].startswith("/repos/teledyne/openkm-brain/actions/runs/810/jobs?")


def test_runs_are_read_lazily_so_asking_for_the_latest_few_reads_one_page() -> None:
    client = RecordingClient([{"workflow_runs": [{"id": n} for n in range(PAGE_SIZE, 0, -1)]}])

    runs = client.latest_runs("teledyne", "openkm-brain", 5)

    assert [r["id"] for r in runs] == [50, 49, 48, 47, 46]
    assert len(client.requested) == 1


def test_runs_not_newest_first_are_refused_rather_than_labelled_latest() -> None:
    client = RecordingClient([{"workflow_runs": [{"id": n} for n in range(1, 4)]}])

    with pytest.raises(GiteaError, match="no longer newest first"):
        client.latest_runs("teledyne", "openkm-brain", 3)


class FakeAdmin:
    def list_run_jobs(self, owner: str, name: str, run_id: int) -> list[dict[str, Any]]:
        return [_job(name="Test [/api]"), NEVER_TAKEN]

    def latest_runs(self, owner: str, name: str, count: int) -> list[dict[str, Any]]:
        return [{"id": 810, "status": "completed", "started_at": "2026-10-09T02:20:39Z"}]


@pytest.fixture
def cli(monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setattr(services, "_gitea_clients", lambda env: (FakeAdmin(), None, "", "https://forge.invalid"))
    return CliRunner()


@pytest.mark.parametrize("args", [["--run", "810"], []])
def test_a_job_name_that_looks_like_rich_markup_is_printed_not_parsed(cli: CliRunner, args: list[str]) -> None:
    result = cli.invoke(services.app, ["gitea", "jobs", "--env", "prod", "--repo", "teledyne/openkm-brain", *args])

    assert result.exit_code == 0, result.output


def test_last_below_one_is_refused_as_bad_input(cli: CliRunner) -> None:
    result = cli.invoke(services.app, ["gitea", "jobs", "--env", "prod", "--repo", "a/b", "--last", "-1"])

    assert result.exit_code == 2
