"""#2194: `test_pods_running_in_namespace` judges a CronJob by its newest outcome.

A CronJob keeps failed Jobs until another failure rotates them out, so a failure
fixed days ago kept `make test-infra` red. The live check excuses a Failed pod
only when a later run of the same CronJob completed; these fixtures pin that.
"""

from __future__ import annotations

from typing import Any

from tests.infra.test_k3s import _pods_not_running


def _job(name: str, created: str, *, cronjob: str | None = "watcher", complete: bool = False) -> dict[str, Any]:
    meta: dict[str, Any] = {"name": name, "creationTimestamp": created}
    if cronjob:
        meta["ownerReferences"] = [{"kind": "CronJob", "name": cronjob}]
    conditions = [{"type": "Complete", "status": "True"}] if complete else []
    return {"metadata": meta, "status": {"conditions": conditions}}


def _pod(name: str, phase: str, job: str | None = None) -> dict[str, Any]:
    meta: dict[str, Any] = {"name": name}
    if job:
        meta["ownerReferences"] = [{"kind": "Job", "name": job}]
    return {"metadata": meta, "status": {"phase": phase}}


FAILED = _job("watcher-1", "2026-10-09T00:00:00Z")
FAILED_POD = _pod("watcher-1-x", "Failed", "watcher-1")


def test_a_failure_a_later_run_fixed_is_excused() -> None:
    later = _job("watcher-2", "2026-10-10T00:00:00Z", complete=True)
    assert _pods_not_running([FAILED_POD], [FAILED, later]) == []


def test_a_later_run_still_in_flight_does_not_excuse_it() -> None:
    later = _job("watcher-2", "2026-10-10T00:00:00Z")
    assert _pods_not_running([FAILED_POD], [FAILED, later]) == ["watcher-1-x (Failed)"]


def test_only_an_earlier_success_does_not_excuse_it() -> None:
    earlier = _job("watcher-0", "2026-10-08T00:00:00Z", complete=True)
    assert _pods_not_running([FAILED_POD], [earlier, FAILED]) == ["watcher-1-x (Failed)"]


def test_another_cronjob_success_does_not_excuse_it() -> None:
    other = _job("other-2", "2026-10-10T00:00:00Z", cronjob="other", complete=True)
    assert _pods_not_running([FAILED_POD], [FAILED, other]) == ["watcher-1-x (Failed)"]


def test_a_failed_pod_with_no_cronjob_behind_it_is_reported() -> None:
    bare = _job("once", "2026-10-09T00:00:00Z", cronjob=None)
    later = _job("watcher-2", "2026-10-10T00:00:00Z", complete=True)
    pods = [_pod("once-x", "Failed", "once"), _pod("evicted", "Failed")]
    assert _pods_not_running(pods, [bare, FAILED, later]) == ["once-x (Failed)", "evicted (Failed)"]


def test_a_pending_pod_is_reported_whatever_its_cronjob_did() -> None:
    """Only a finished failure is history; a pod still Pending is a live problem."""
    stuck = _job("watcher-1", "2026-10-09T00:00:00Z")
    later = _job("watcher-2", "2026-10-10T00:00:00Z", complete=True)
    pods = [_pod("watcher-1-x", "Pending", "watcher-1"), _pod("api", "Running")]
    assert _pods_not_running(pods, [stuck, later]) == ["watcher-1-x (Pending)"]
