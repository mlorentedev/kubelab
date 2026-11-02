"""OPS-043 (#2580): every CronJob's finished Jobs expire by age, not only by count.

`failedJobsHistoryLimit` bounds how many failed Jobs are kept, never for how
long, so a single transient failure of a watcher stays until a newer failure
evicts it. On 2026-10-21 staging held a failed `disk-watcher` Job 56 days old,
red in the Argo CD tree, while every run since had succeeded. The
Application's health was never affected: Argo CD grades it from managed
resources only, and a Job a CronJob creates is a child (see #2580).

A TTL on the Job template bounds the age instead. A day keeps a failure in
view for the next working session; the watcher's verdict itself lives in Loki
and its alert, not in the Job object. The TTL applies to Jobs created from the
new template: the Jobs already retained stay until the history limit evicts
them.

The check reads the rendered overlays, so a CronJob added in an overlay is
held to the same rule as one in the base.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
MAX_TTL_SECONDS = 86400


def _cronjobs(overlay: str) -> list[dict]:
    if shutil.which("kubectl") is None:
        pytest.skip(f"kubectl not on PATH: the {overlay} CronJobs were NOT checked")
    rendered = subprocess.run(
        ["kubectl", "kustomize", str(ROOT / f"infra/k8s/overlays/{overlay}")],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [doc for doc in yaml.safe_load_all(rendered) if doc and doc.get("kind") == "CronJob"]


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_the_overlay_renders_cronjobs(overlay: str) -> None:
    # Guards the check below against passing on an empty list.
    assert _cronjobs(overlay), f"{overlay} renders no CronJob: the TTL check would hold nothing"


@pytest.mark.parametrize("overlay", ["staging", "prod"])
def test_every_cronjob_expires_its_finished_jobs_within_a_day(overlay: str) -> None:
    missing = {}
    for cronjob in _cronjobs(overlay):
        ttl = cronjob["spec"]["jobTemplate"]["spec"].get("ttlSecondsAfterFinished")
        if not isinstance(ttl, int) or not 0 < ttl <= MAX_TTL_SECONDS:
            missing[cronjob["metadata"]["name"]] = ttl
    assert not missing, f"{overlay}: CronJobs whose finished Jobs never expire by age (or not within a day): {missing}"
