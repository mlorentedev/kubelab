"""The R2 watcher's CronJob runs the probe it claims to run (BACKUP-055 AC1, R4).

`test_r2_backup_watcher_probe.py` proves what `probe.sh` prints. None of that
matters unless the pod actually runs that file, in the pinned image, with the
read-only Secret, against the committed targets, and lives long enough to print
its verdict. Every expected value here is read from its source of truth (the
probe's own defaults, `common.yaml`, the Ansible role, the Secret mapping), so a
change to one side without the other goes red instead of drifting.

Rendered, not read from the source file: the image tag only exists after
Kustomize's `images:` transform, and the ConfigMap name only after its hash.
"""

from __future__ import annotations

import pathlib
import re
import shutil
import subprocess

import pytest
import yaml

from toolkit.features.k8s_secrets import SECRET_DEFINITIONS

REPO = pathlib.Path(__file__).resolve().parent.parent
WATCHER_DIR = REPO / "infra/k8s/base/services/r2-backup-watcher"
PROBE = WATCHER_DIR / "probe.sh"
SIZE = WATCHER_DIR / "size.sh"
TARGETS = WATCHER_DIR / "targets.txt"
COMMON = REPO / "infra/config/values/common.yaml"
NODE_BACKUP_DEFAULTS = REPO / "infra/ansible/roles/node_backup/defaults/main.yml"

ENVIRONMENTS = ("staging", "prod")
NAME = "r2-backup-watcher"


def _probe_default(var: str, script: pathlib.Path = PROBE) -> str:
    """The value a script falls back to for `$var`, e.g. `${STAGING_DIR:-...}`."""
    match = re.search(rf"\$\{{{var}:-([^}}]*)\}}", script.read_text())
    assert match, f"{script.name} has no ${{{var}:-...}} default"
    return match.group(1)


def _targets() -> list[list[str]]:
    lines = TARGETS.read_text().splitlines()
    return [line.split() for line in lines if line.strip() and not line.startswith("#")]


def _target_nodes() -> int:
    return len(_targets())


def _target_buckets() -> int:
    """Distinct buckets in the repository URLs, `s3:https://<host>/<bucket>/<prefix>`."""
    return len({fields[1].split("://", 1)[1].split("/")[1] for fields in _targets()})


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


@pytest.fixture(params=ENVIRONMENTS, scope="module")
def rendered(request) -> dict:
    docs = _kustomize(request.param)
    cronjob = next(d for d in docs if d["kind"] == "CronJob" and d["metadata"]["name"] == NAME)
    job = cronjob["spec"]["jobTemplate"]["spec"]
    pod = job["template"]["spec"]
    (container,) = pod["containers"]
    (init,) = pod["initContainers"]
    configmaps = {d["metadata"]["name"]: d for d in docs if d["kind"] == "ConfigMap"}
    return {"cronjob": cronjob, "job": job, "pod": pod, "container": container, "init": init, "configmaps": configmaps}


def test_probe_reads_the_paths_the_nodes_write() -> None:
    """The probe looks for the staging dir and the sentinel where `node_backup` puts them.

    A rename on the node side would otherwise turn every node `missing` +
    `no capture sentinel` while the backups are fine, or, worse, a probe edited
    to match a wrong path would stop checking anything real.
    """
    defaults = yaml.safe_load(NODE_BACKUP_DEFAULTS.read_text())
    staging = defaults["node_backup_staging_dir"]
    sentinel = defaults["node_backup_capture_sentinel"].replace("{{ node_backup_staging_dir }}", staging)

    assert _probe_default("STAGING_DIR") == staging
    assert f"{staging}/{_probe_default('SENTINEL')}" == sentinel


def test_runs_the_pinned_restic_image(rendered: dict) -> None:
    expected = yaml.safe_load(COMMON.read_text())["backup"]["watcher"]["image"]
    assert rendered["container"]["image"] == expected


def test_sizes_with_the_pinned_rclone_image(rendered: dict) -> None:
    """BACKUP-075: an exact tag from `common.yaml`, never a floating one."""
    expected = yaml.safe_load(COMMON.read_text())["backup"]["watcher"]["size_image"]
    assert re.fullmatch(r"rclone/rclone:\d+\.\d+\.\d+", expected), expected
    assert rendered["init"]["name"] == "r2-size"
    assert rendered["init"]["image"] == expected


def test_the_sizing_step_gets_only_the_read_only_token(rendered: dict) -> None:
    """Listing needs the S3 pair and nothing else: never the restic password."""
    (mapping,) = [m for m in SECRET_DEFINITIONS if m.name.startswith(NAME)]
    init = rendered["init"]
    assert "envFrom" not in init
    from_secret = {
        e["name"]: e["valueFrom"]["secretKeyRef"] for e in init.get("env", []) if "valueFrom" in e
    }
    assert set(from_secret) == {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"}
    assert {ref["name"] for ref in from_secret.values()} == {mapping.name}
    assert all(ref["key"] == name for name, ref in from_secret.items())


def test_the_sizing_step_is_locked_down(rendered: dict) -> None:
    context = rendered["init"]["securityContext"]
    assert context["readOnlyRootFilesystem"] is True
    assert context["allowPrivilegeEscalation"] is False
    assert context["capabilities"]["drop"] == ["ALL"]


def test_the_probe_reads_the_file_the_sizing_step_writes(rendered: dict) -> None:
    """One emptyDir, written by the init container and mounted read-only by the probe, at the path both default to."""
    sizes = _probe_default("WATCHER_SIZES")
    assert _probe_default("WATCHER_SIZES", SIZE) == sizes
    directory = str(pathlib.PurePosixPath(sizes).parent)
    writer = {m["mountPath"]: m for m in rendered["init"]["volumeMounts"]}[directory]
    reader = {m["mountPath"]: m for m in rendered["container"]["volumeMounts"]}[directory]
    assert writer["name"] == reader["name"]
    assert not writer.get("readOnly", False) and reader["readOnly"] is True
    volume = next(v for v in rendered["pod"]["volumes"] if v["name"] == writer["name"])
    assert "emptyDir" in volume


def test_the_sizing_step_runs_the_committed_script(rendered: dict) -> None:
    mount_dir = str(pathlib.PurePosixPath(_probe_default("WATCHER_TARGETS")).parent)
    mounts = {m["mountPath"]: m["name"] for m in rendered["init"]["volumeMounts"]}
    volume = next(v for v in rendered["pod"]["volumes"] if v["name"] == mounts[mount_dir])
    configmap = rendered["configmaps"][volume["configMap"]["name"]]
    assert configmap["data"]["size.sh"] == SIZE.read_text()
    assert rendered["init"]["command"] + rendered["init"].get("args", []) == ["/bin/sh", f"{mount_dir}/size.sh"]


def test_reads_the_read_only_secret(rendered: dict) -> None:
    (mapping,) = [m for m in SECRET_DEFINITIONS if m.name.startswith(NAME)]
    refs = [e["secretRef"]["name"] for e in rendered["container"].get("envFrom", []) if "secretRef" in e]
    assert refs == [mapping.name]


def test_runs_the_committed_probe_against_the_committed_targets(rendered: dict) -> None:
    """The mounted files are byte-equal to the ones the probe tests exercised."""
    mount_dir = str(pathlib.PurePosixPath(_probe_default("WATCHER_TARGETS")).parent)
    mounts = {m["mountPath"]: m["name"] for m in rendered["container"]["volumeMounts"]}
    assert mount_dir in mounts, f"nothing mounted at {mount_dir}, where the probe reads its targets"

    volume = next(v for v in rendered["pod"]["volumes"] if v["name"] == mounts[mount_dir])
    configmap = rendered["configmaps"][volume["configMap"]["name"]]
    assert configmap["data"]["probe.sh"] == PROBE.read_text()
    assert configmap["data"]["targets.txt"] == TARGETS.read_text()

    # Run by `sh`, not by its mode bits, and without `-e`: the probe owns its exits.
    command = rendered["container"]["command"] + rendered["container"].get("args", [])
    assert command == ["/bin/sh", f"{mount_dir}/probe.sh"]


def test_one_run_is_one_verdict(rendered: dict) -> None:
    """No retries and no overlap: each Job prints exactly one fleet line.

    A retried pod would print a second verdict, and the rule's `last_over_time`
    reads only the last one, so a flaky pass could overwrite a real failure.
    """
    assert rendered["cronjob"]["spec"]["concurrencyPolicy"] == "Forbid"
    assert rendered["job"]["backoffLimit"] == 0
    assert rendered["pod"]["restartPolicy"] == "Never"


def _restic_calls_per_node() -> int:
    """The timed restic calls the probe makes per node, counted from its source.

    Hardcoding the count is how this test kept passing after BACKUP-058 added a
    third call and the worst case outgrew the deadline (review, 2026-09-30).
    """
    source = PROBE.read_text()
    return len(re.findall(r"\$\(restic_read ", source))


def test_lives_long_enough_to_report(rendered: dict) -> None:
    """R4 in the pod: a deadline kill must still let the probe print its line.

    Kubelet signals PID 1 only, and `sh` runs its trap only once its foreground
    child returns, which can take one full timeout. So the deadline has to
    outlast the worst-case probe (every call timing out on every node), and the
    grace period has to outlast the longest single call; otherwise SIGKILL
    lands first and the Job ends silent, which the rule reads as noData only
    after 24h.
    """
    timeout = int(_probe_default("RESTIC_TIMEOUT"))
    size_timeout = int(_probe_default("SIZE_TIMEOUT", SIZE))
    calls = _restic_calls_per_node()
    assert calls >= 3, f"counted {calls} restic_read calls in probe.sh; the pattern is stale"
    assert len(re.findall(r"^\s*measure (?:bucket|node) ", SIZE.read_text(), re.M)) == 2, "size.sh's calls are stale"
    # The init container runs first: one listing per bucket and one per node.
    sizing = (_target_buckets() + _target_nodes()) * size_timeout
    worst_case = sizing + _target_nodes() * calls * timeout
    assert rendered["job"]["activeDeadlineSeconds"] > worst_case
    assert rendered["pod"]["terminationGracePeriodSeconds"] > timeout


def test_needs_no_cluster_api(rendered: dict) -> None:
    assert rendered["pod"]["serviceAccountName"] == NAME
    assert rendered["pod"]["automountServiceAccountToken"] is False


def test_has_a_writable_tmp(rendered: dict) -> None:
    """`mktemp` in the probe needs it; the root filesystem is read-only."""
    assert rendered["container"]["securityContext"]["readOnlyRootFilesystem"] is True
    mounts = {m["mountPath"]: m["name"] for m in rendered["container"]["volumeMounts"]}
    assert "/tmp" in mounts
    volume = next(v for v in rendered["pod"]["volumes"] if v["name"] == mounts["/tmp"])
    assert "emptyDir" in volume
