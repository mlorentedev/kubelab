"""#2194: `test_pods_running_in_namespace` judges a CronJob by its newest outcome.

A CronJob keeps failed Jobs until another failure rotates them out, so a failure
fixed days ago kept `make test-infra` red. The live check excuses a Failed pod
only when a run of the same CronJob completed after the pod failed; these
fixtures pin that.
"""

from __future__ import annotations

from typing import Any

from tests.infra.test_k3s import _pods_not_running


def _job(name: str, *, cronjob: str | None = "watcher", completed: str | None = None) -> dict[str, Any]:
    """A Job; `completed` is its `status.completionTime`, and only a completed Job has one."""
    meta: dict[str, Any] = {"name": name}
    if cronjob:
        meta["ownerReferences"] = [{"kind": "CronJob", "name": cronjob}]
    status: dict[str, Any] = {"conditions": [{"type": "Complete", "status": "True"}] if completed else []}
    if completed:
        status["completionTime"] = completed
    return {"metadata": meta, "status": status}


def _pod(name: str, phase: str, job: str | None = None, *, finished: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {"name": name}
    if job:
        meta["ownerReferences"] = [{"kind": "Job", "name": job}]
    status: dict[str, Any] = {"phase": phase}
    if finished:
        status["containerStatuses"] = [{"state": {"terminated": {"finishedAt": finished}}}]
    return {"metadata": meta, "status": status}


FAILED = _job("watcher-1")
FAILED_POD = _pod("watcher-1-x", "Failed", "watcher-1", finished="2026-10-09T00:05:00Z")


def test_a_failure_a_later_run_fixed_is_excused() -> None:
    later = _job("watcher-2", completed="2026-10-10T00:05:00Z")
    assert _pods_not_running([FAILED_POD], [FAILED, later]) == []


def test_a_later_run_still_in_flight_does_not_excuse_it() -> None:
    later = _job("watcher-2")
    assert _pods_not_running([FAILED_POD], [FAILED, later]) == ["watcher-1-x (Failed)"]


def test_only_an_earlier_success_does_not_excuse_it() -> None:
    earlier = _job("watcher-0", completed="2026-10-08T00:05:00Z")
    assert _pods_not_running([FAILED_POD], [earlier, FAILED]) == ["watcher-1-x (Failed)"]


def test_a_success_that_finished_before_the_failure_does_not_excuse_it() -> None:
    """Overlapping runs: the newer Job completed first, then the older one failed.
    The newest outcome is the failure, whichever Job was created later."""
    overlapping = _job("watcher-2", completed="2026-10-09T00:04:00Z")
    assert _pods_not_running([FAILED_POD], [FAILED, overlapping]) == ["watcher-1-x (Failed)"]


def test_a_failed_pod_with_no_recorded_finish_is_reported() -> None:
    unfinished = _pod("watcher-1-x", "Failed", "watcher-1")
    later = _job("watcher-2", completed="2026-10-10T00:05:00Z")
    assert _pods_not_running([unfinished], [FAILED, later]) == ["watcher-1-x (Failed)"]


def test_another_cronjob_success_does_not_excuse_it() -> None:
    other = _job("other-2", cronjob="other", completed="2026-10-10T00:05:00Z")
    assert _pods_not_running([FAILED_POD], [FAILED, other]) == ["watcher-1-x (Failed)"]


def test_a_failed_pod_with_no_cronjob_behind_it_is_reported() -> None:
    bare = _job("once", cronjob=None)
    later = _job("watcher-2", completed="2026-10-10T00:05:00Z")
    pods = [
        _pod("once-x", "Failed", "once", finished="2026-10-09T00:05:00Z"),
        _pod("evicted", "Failed", finished="2026-10-09T00:05:00Z"),
    ]
    assert _pods_not_running(pods, [bare, FAILED, later]) == ["once-x (Failed)", "evicted (Failed)"]


def test_a_pending_pod_is_reported_whatever_its_cronjob_did() -> None:
    """Only a finished failure is history; a pod still Pending is a live problem."""
    stuck = _job("watcher-1")
    later = _job("watcher-2", completed="2026-10-10T00:05:00Z")
    pods = [_pod("watcher-1-x", "Pending", "watcher-1"), _pod("api", "Running")]
    assert _pods_not_running(pods, [stuck, later]) == ["watcher-1-x (Pending)"]


def test_the_latest_container_finish_is_the_failure_time() -> None:
    pod = _pod("watcher-1-x", "Failed", "watcher-1", finished="2026-10-09T00:05:00Z")
    pod["status"]["containerStatuses"].append({"state": {"terminated": {"finishedAt": "2026-10-11T00:00:00Z"}}})
    between = _job("watcher-2", completed="2026-10-10T00:05:00Z")
    assert _pods_not_running([pod], [FAILED, between]) == ["watcher-1-x (Failed)"]
