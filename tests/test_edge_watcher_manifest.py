"""The edge watcher's CronJob, as both overlays render it (NET-005 AC12).

Read from `kubectl kustomize`, never from the base file: the image tag and the
ConfigMap's hashed name exist only in the render.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WATCHER_DIR = REPO / "infra/k8s/base/services/edge-watcher"
PROBE = WATCHER_DIR / "probe.sh"
TARGETS = WATCHER_DIR / "targets.txt"
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
NAME = "edge-watcher"


def _probe_default(var: str) -> str:
    match = re.search(rf"\$\{{{var}:-([^}}]*)\}}", PROBE.read_text())
    assert match, f"probe.sh has no ${{{var}:-...}} default"
    return match.group(1)


def _kustomize(env: str) -> list[dict]:
    """Render an overlay, or skip loudly: a skip means CANNOT CHECK, never a pass."""
    if shutil.which("kubectl") is None:
        pytest.skip("CANNOT CHECK: kubectl is not installed, so the watcher render is unverified.")
    result = subprocess.run(
        ["kubectl", "kustomize", str(REPO / "infra/k8s/overlays" / env)],
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(f"kubectl kustomize overlays/{env} failed:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


@pytest.fixture(params=("staging", "prod"), scope="module")
def rendered(request) -> dict:
    docs = _kustomize(request.param)
    cronjob = next(d for d in docs if d["kind"] == "CronJob" and d["metadata"]["name"] == NAME)
    job = cronjob["spec"]["jobTemplate"]["spec"]
    pod = job["template"]["spec"]
    (container,) = pod["containers"]
    configmaps = {d["metadata"]["name"]: d for d in docs if d["kind"] == "ConfigMap"}
    return {"cronjob": cronjob, "job": job, "pod": pod, "container": container, "configmaps": configmaps}


def test_runs_the_pinned_restic_image(rendered: dict) -> None:
    """The R2 watcher's image, whose `nc -z -w` already reaches these nodes from prod."""
    assert rendered["container"]["image"] == COMMON["backup"]["watcher"]["image"]


def test_runs_the_committed_probe_against_the_committed_targets(rendered: dict) -> None:
    mount_dir = str(pathlib.PurePosixPath(_probe_default("EDGE_TARGETS")).parent)
    mounts = {m["mountPath"]: m["name"] for m in rendered["container"]["volumeMounts"]}
    assert mount_dir in mounts, f"nothing mounted at {mount_dir}, where the probe reads its targets"
    volume = next(v for v in rendered["pod"]["volumes"] if v["name"] == mounts[mount_dir])
    name = volume["configMap"]["name"]
    assert re.fullmatch(r"edge-watcher-probe-[a-z0-9]{10}", name), f"{name} carries no hash suffix"
    configmap = rendered["configmaps"][name]
    assert configmap["data"]["probe.sh"] == PROBE.read_text()
    assert configmap["data"]["targets.txt"] == TARGETS.read_text()
    command = rendered["container"]["command"] + rendered["container"].get("args", [])
    assert command == ["/bin/sh", f"{mount_dir}/probe.sh"]


def test_one_run_is_one_report(rendered: dict) -> None:
    """A retried pod would print every target twice in one run."""
    assert rendered["cronjob"]["spec"]["concurrencyPolicy"] == "Forbid"
    assert rendered["job"]["backoffLimit"] == 0
    assert rendered["pod"]["restartPolicy"] == "Never"


def test_lives_long_enough_to_report_every_target(rendered: dict) -> None:
    """Each target is bounded at REACH_TIMEOUT + 2 seconds; the deadline must outlast all of them hung."""
    targets = [line for line in TARGETS.read_text().splitlines() if line.strip() and not line.startswith("#")]
    worst_case = len(targets) * (int(_probe_default("REACH_TIMEOUT")) + 2)
    assert rendered["job"]["activeDeadlineSeconds"] > worst_case


def test_runs_every_five_minutes(rendered: dict) -> None:
    assert rendered["cronjob"]["spec"]["schedule"] == "*/5 * * * *"


def test_needs_no_cluster_api_and_no_privilege(rendered: dict) -> None:
    pod, container = rendered["pod"], rendered["container"]
    assert pod["serviceAccountName"] == NAME
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["securityContext"]["capabilities"]["drop"] == ["ALL"]
