"""Run a CronJob once, on demand, and report its verdict (TOOL-084).

The watchers here (`r2-backup-watcher`, the disk and backup probes) are CronJobs
whose output IS the check: a JSON line per subject in the Job's log, shipped to
Loki. Re-checking now instead of waiting for the next schedule used to be three
hand-typed commands from a runbook: `kubectl create job --from=cronjob/...`,
`kubectl logs`, `kubectl delete`.

`--from` has a trap on top of being manual. It sets an ownerReference to the
CronJob, so the CronJob controller adopts the Job and counts it against
`failedJobsHistoryLimit`: a failed manual run can be pruned, pod and log
included, before anyone has read it (seen on staging during BACKUP-055,
2026-09-27). The Job built here copies the CronJob's `jobTemplate` and carries
NO ownerReference, so the controller never sees it and only this code removes it.

As in `pvc_drill`, the removal is a `finally` in the same call that reads the
result. It is never a second command: Ctrl-C during the wait still deletes the
Job. The log is read before the delete, so the verdict survives the cleanup.
"""

from __future__ import annotations

import copy
import json
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

NAMESPACE = "kubelab"

#: Used when the jobTemplate declares no `activeDeadlineSeconds`. With one, the
#: wait is that deadline plus scheduling headroom, since Kubernetes itself ends
#: the Job there.
DEFAULT_TIMEOUT_S = 900
SCHEDULING_HEADROOM_S = 120
DEFAULT_POLL_S = 5

#: Annotations that describe the CronJob object itself, never its Jobs. Argo
#: CD's tracking id in particular must not be copied: a Job carrying it would be
#: claimed by the Application and pruned as drift.
_CRONJOB_ONLY_ANNOTATIONS = ("argocd.argoproj.io/", "kubectl.kubernetes.io/last-applied-configuration")


class CronJobRunTeardownError(Exception):
    """The manual Job could not be deleted and is still in the cluster.

    Raised from the `finally`, so it replaces the result. A leftover Job is not
    harmless here: it keeps its pod and, for a watcher, its credentials mounted.
    """


@dataclass(frozen=True)
class CronJobRunResult:
    #: `succeeded`, `failed`, or `timeout` (the Job had not finished when the
    #: wait ended). `timeout` is not a pass: nothing reported a verdict.
    outcome: str
    log: str
    waited_s: float


def manual_job_name(cronjob_name: str, stamp: str) -> str:
    """`<cronjob>-manual-<stamp>`, truncated so the whole name is a DNS label (<=63)."""
    suffix = f"-manual-{stamp}"
    return cronjob_name[: 63 - len(suffix)].rstrip("-") + suffix


def job_from_cronjob(cronjob: dict[str, Any], name: str) -> dict[str, Any]:
    """The Job the CronJob would start, minus the ownerReference. Pure."""
    template = copy.deepcopy(cronjob["spec"]["jobTemplate"])
    metadata = template.get("metadata") or {}
    annotations = {
        k: v for k, v in (metadata.get("annotations") or {}).items() if not k.startswith(_CRONJOB_ONLY_ANNOTATIONS)
    }
    # Kubernetes' own marker for a Job started by hand from a CronJob; the same
    # one `kubectl create job --from` writes.
    annotations["cronjob.kubernetes.io/instantiate"] = "manual"
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": name,
            "namespace": cronjob["metadata"].get("namespace", NAMESPACE),
            "labels": dict(metadata.get("labels") or {}),
            "annotations": annotations,
        },
        "spec": template["spec"],
    }


def job_outcome(job: dict[str, Any]) -> str | None:
    """`succeeded` / `failed` once a FINAL condition is true, else None.

    Only `Complete` and `Failed` are final. Since Kubernetes 1.31 a Job reports
    `SuccessCriteriaMet` / `FailureTarget` first, while its pods are still being
    terminated; reading those as the end would delete a Job mid-teardown.
    """
    for condition in (job.get("status") or {}).get("conditions") or []:
        if condition.get("status") != "True":
            continue
        if condition.get("type") == "Complete":
            return "succeeded"
        if condition.get("type") == "Failed":
            return "failed"
    return None


def wait_budget_s(cronjob: dict[str, Any]) -> float:
    deadline = cronjob["spec"]["jobTemplate"]["spec"].get("activeDeadlineSeconds")
    return float(deadline + SCHEDULING_HEADROOM_S) if deadline else float(DEFAULT_TIMEOUT_S)


def run_cronjob(
    *,
    job_name: str,
    get_cronjob: Callable[[], dict[str, Any]],
    create: Callable[[dict[str, Any]], None],
    get_job: Callable[[], dict[str, Any]],
    logs: Callable[[], str],
    delete: Callable[[], None],
    timeout_s: float | None = None,
    poll_s: float = DEFAULT_POLL_S,
    sleep: Callable[[float], None] = time.sleep,
    now: Callable[[], float] = time.monotonic,
    log: Callable[[str], None] = print,
) -> CronJobRunResult:
    """Create the Job, wait for a final condition, read its log, delete it. Always.

    Every side effect is injected, so the control flow, including deletion on
    interrupt, is exercised without a cluster.
    """
    cronjob = get_cronjob()
    budget = timeout_s if timeout_s is not None else wait_budget_s(cronjob)
    job = job_from_cronjob(cronjob, job_name)

    started = now()
    outcome: str | None = None
    try:
        create(job)
        log(f"{job_name}: created; waiting up to {budget / 60:.0f}m")
        while True:
            outcome = job_outcome(get_job())
            if outcome is not None or now() - started >= budget:
                break
            sleep(poll_s)
        output = logs()
        return CronJobRunResult(outcome=outcome or "timeout", log=output, waited_s=now() - started)
    finally:
        try:
            delete()
            log(f"{job_name}: deleted")
        except Exception as exc:  # noqa: BLE001 -- re-raised as CronJobRunTeardownError
            raise CronJobRunTeardownError(
                f"Job {job_name} could not be deleted and is still in the cluster. "
                f"Remove it before it is mistaken for a scheduled run: kubectl delete job {job_name} -n {NAMESPACE}"
            ) from exc


# --- kubectl adapters --------------------------------------------------------


def _kubectl(kubeconfig: str, *args: str) -> list[str]:
    return ["kubectl", "--kubeconfig", kubeconfig, "-n", NAMESPACE, *args]


def get_cronjob(kubeconfig: str, name: str) -> dict[str, Any]:
    proc = subprocess.run(_kubectl(kubeconfig, "get", "cronjob", name, "-o", "json"), capture_output=True, text=True)
    if proc.returncode != 0:
        raise LookupError(f"CronJob {name} not found in {NAMESPACE}: {proc.stderr.strip()}")
    return json.loads(proc.stdout)


def create_job(kubeconfig: str, job: dict[str, Any]) -> None:
    subprocess.run(
        _kubectl(kubeconfig, "create", "-f", "-"), input=json.dumps(job), capture_output=True, text=True, check=True
    )


def get_job(kubeconfig: str, name: str) -> dict[str, Any]:
    proc = subprocess.run(
        _kubectl(kubeconfig, "get", "job", name, "-o", "json"), capture_output=True, text=True, check=True
    )
    return json.loads(proc.stdout)


def job_logs(kubeconfig: str, name: str) -> str:
    # Not check=True: a pod that never started has no log, and "no log" is
    # information for the caller, not a reason to skip the delete.
    proc = subprocess.run(
        _kubectl(kubeconfig, "logs", f"job/{name}", "--all-containers=true"), capture_output=True, text=True
    )
    return proc.stdout if proc.returncode == 0 else f"(no log: {proc.stderr.strip()})\n"


def delete_job(kubeconfig: str, name: str) -> None:
    # Background propagation removes the pod with the Job; --ignore-not-found
    # makes the finally safe when creation never happened.
    subprocess.run(
        _kubectl(kubeconfig, "delete", "job", name, "--ignore-not-found", "--wait=false", "--cascade=background"),
        capture_output=True,
        text=True,
        check=True,
    )
