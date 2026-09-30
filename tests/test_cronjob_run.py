"""`make watcher-run`: run a CronJob once, on demand, and report its verdict (TOOL-084).

The only way to do this used to be `kubectl create job --from=cronjob/...`, then
`kubectl logs`, then `kubectl delete`: three hand-typed commands, documented in a
runbook that otherwise says operations go through Makefile/toolkit. And `--from`
has a measured trap: it sets an ownerReference to the CronJob, so the CronJob
controller adopts the Job and prunes it under `failedJobsHistoryLimit`, pod and
log included, possibly before anyone has read it (BACKUP-055, 2026-09-27).

These tests pin what the target promises:
- the Job is built from the CronJob's `jobTemplate` and carries NO ownerReference;
- the log is read before the Job is deleted, and the Job is deleted always;
- the result reflects the Job's outcome, and a run that never finished is not a pass.
"""

from __future__ import annotations

import subprocess

import pytest

from toolkit.features import cronjob_run
from toolkit.features.cronjob_run import (
    CronJobRunTeardownError,
    KubectlError,
    job_from_cronjob,
    job_outcome,
    manual_job_name,
    run_cronjob,
)

CRONJOB = {
    "apiVersion": "batch/v1",
    "kind": "CronJob",
    "metadata": {
        "name": "r2-backup-watcher",
        "namespace": "kubelab",
        "uid": "abc-123",
        "annotations": {"argocd.argoproj.io/tracking-id": "kubelab-prod:batch/CronJob:kubelab/r2-backup-watcher"},
    },
    "spec": {
        "schedule": "0 */6 * * *",
        "failedJobsHistoryLimit": 3,
        "jobTemplate": {
            "metadata": {"labels": {"app.kubernetes.io/name": "r2-backup-watcher"}},
            "spec": {
                "backoffLimit": 0,
                "activeDeadlineSeconds": 600,
                "template": {"spec": {"restartPolicy": "Never", "containers": [{"name": "probe", "image": "x"}]}},
            },
        },
    },
}


def test_the_job_carries_the_template_and_no_owner_reference() -> None:
    job = job_from_cronjob(CRONJOB, "r2-backup-watcher-manual-0732")
    assert job["kind"] == "Job"
    assert job["metadata"]["name"] == "r2-backup-watcher-manual-0732"
    assert job["metadata"]["namespace"] == "kubelab"
    assert "ownerReferences" not in job["metadata"]
    assert job["spec"] == CRONJOB["spec"]["jobTemplate"]["spec"]
    assert job["metadata"]["labels"]["app.kubernetes.io/name"] == "r2-backup-watcher"
    # Kubernetes' own marker for a Job started by hand from a CronJob.
    assert job["metadata"]["annotations"]["cronjob.kubernetes.io/instantiate"] == "manual"


def test_the_job_does_not_inherit_the_cronjobs_argo_tracking() -> None:
    job = job_from_cronjob(CRONJOB, "x")
    assert "argocd.argoproj.io/tracking-id" not in job["metadata"].get("annotations", {})


def test_building_the_job_does_not_mutate_the_cronjob() -> None:
    before = repr(CRONJOB)
    job = job_from_cronjob(CRONJOB, "x")
    job["spec"]["backoffLimit"] = 9
    job["metadata"]["labels"]["extra"] = "y"
    assert repr(CRONJOB) == before


def test_the_manual_job_name_is_a_valid_dns_label() -> None:
    name = manual_job_name("a" * 70, "20260930t073200")
    assert len(name) <= 63
    assert name.endswith("-manual-20260930t073200")
    assert name[0].isalnum() and name[-1].isalnum()


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ({}, None),
        ({"active": 1}, None),
        ({"conditions": [{"type": "Complete", "status": "True"}]}, "succeeded"),
        ({"conditions": [{"type": "Failed", "status": "True"}]}, "failed"),
        ({"conditions": [{"type": "Failed", "status": "False"}]}, None),
        # A terminating Job reports SuccessCriteriaMet/FailureTarget first; only
        # Complete/Failed are final.
        ({"conditions": [{"type": "FailureTarget", "status": "True"}]}, None),
    ],
)
def test_the_outcome_is_read_from_final_conditions_only(status: dict, expected: str | None) -> None:
    assert job_outcome({"status": status}) == expected


class FakeCluster:
    def __init__(self, outcomes: list[str | None], delete_fails: bool = False) -> None:
        self.outcomes = outcomes
        self.delete_fails = delete_fails
        self.calls: list[str] = []
        self.created: dict | None = None

    def get_cronjob(self) -> dict:
        self.calls.append("get_cronjob")
        return CRONJOB

    def create(self, job: dict) -> None:
        self.calls.append("create")
        self.created = job

    def get_job(self) -> dict:
        self.calls.append("get_job")
        outcome = self.outcomes.pop(0) if self.outcomes else None
        conditions = []
        if outcome == "succeeded":
            conditions = [{"type": "Complete", "status": "True"}]
        elif outcome == "failed":
            conditions = [{"type": "Failed", "status": "True"}]
        return {"status": {"conditions": conditions}}

    def logs(self) -> str:
        self.calls.append("logs")
        return '{"metric":"r2_backup_health","healthy":1}\n'

    def delete(self) -> None:
        self.calls.append("delete")
        if self.delete_fails:
            raise RuntimeError("apiserver unreachable")


def _run(cluster: FakeCluster, timeout_s: float = 100) -> object:
    clock = [0.0]
    return run_cronjob(
        job_name="w-manual-1",
        get_cronjob=cluster.get_cronjob,
        create=cluster.create,
        get_job=cluster.get_job,
        logs=cluster.logs,
        delete=cluster.delete,
        timeout_s=timeout_s,
        poll_s=10,
        sleep=lambda s: clock.__setitem__(0, clock[0] + s),
        now=lambda: clock[0],
        log=lambda _: None,
    )


def test_a_succeeded_job_reports_success_with_its_log_read_before_deletion() -> None:
    cluster = FakeCluster([None, None, "succeeded"])
    result = _run(cluster)
    assert result.outcome == "succeeded"
    assert "r2_backup_health" in result.log
    assert cluster.calls.index("logs") < cluster.calls.index("delete")
    assert cluster.created is not None and "ownerReferences" not in cluster.created["metadata"]


def test_a_failed_job_reports_failure_and_is_still_deleted() -> None:
    cluster = FakeCluster(["failed"])
    result = _run(cluster)
    assert result.outcome == "failed"
    assert result.log
    assert cluster.calls[-1] == "delete"


def test_a_job_that_never_finishes_is_not_a_pass() -> None:
    cluster = FakeCluster([])
    result = _run(cluster, timeout_s=30)
    assert result.outcome == "timeout"
    # The partial log is still worth reading: the lines printed before the
    # deadline are verdicts in their own right.
    assert "logs" in cluster.calls
    assert cluster.calls[-1] == "delete"


def test_an_interrupted_wait_still_deletes_the_job() -> None:
    cluster = FakeCluster([])

    def interrupt(_: float) -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        run_cronjob(
            job_name="w-manual-1",
            get_cronjob=cluster.get_cronjob,
            create=cluster.create,
            get_job=cluster.get_job,
            logs=cluster.logs,
            delete=cluster.delete,
            timeout_s=100,
            poll_s=10,
            sleep=interrupt,
            now=lambda: 0.0,
            log=lambda _: None,
        )
    assert cluster.calls[-1] == "delete"


def test_a_failed_teardown_is_raised_not_logged() -> None:
    cluster = FakeCluster(["succeeded"], delete_fails=True)
    with pytest.raises(CronJobRunTeardownError, match="w-manual-1") as caught:
        _run(cluster)
    # The reason travels in the message itself, not only in the chained cause
    # a CLI prints nowhere.
    assert "apiserver unreachable" in str(caught.value)


def test_nothing_is_created_when_the_cronjob_cannot_be_read() -> None:
    cluster = FakeCluster([])

    def missing() -> dict:
        raise LookupError("cronjob not found")

    with pytest.raises(LookupError):
        run_cronjob(
            job_name="w-manual-1",
            get_cronjob=missing,
            create=cluster.create,
            get_job=cluster.get_job,
            logs=cluster.logs,
            delete=cluster.delete,
            timeout_s=100,
            poll_s=10,
            sleep=lambda _: None,
            now=lambda: 0.0,
            log=lambda _: None,
        )
    assert cluster.calls == []


@pytest.mark.parametrize(
    "call",
    [
        lambda: cronjob_run.create_job("kc", {"kind": "Job"}),
        lambda: cronjob_run.get_job("kc", "w-manual-1"),
        lambda: cronjob_run.delete_job("kc", "w-manual-1"),
    ],
    ids=["create", "get", "delete"],
)
def test_a_kubectl_failure_carries_kubectls_own_reason(monkeypatch, call) -> None:
    """A CalledProcessError names the argv and the exit code, never the reason.

    Forbidden, an expired kubeconfig or an unreachable API server all read the
    same without stderr, which is the one thing the operator needs.
    """

    def refuse(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 1, stdout="", stderr='Error from server (Forbidden): jobs.batch is forbidden')

    monkeypatch.setattr(cronjob_run.subprocess, "run", refuse)
    with pytest.raises(KubectlError, match="jobs.batch is forbidden"):
        call()
