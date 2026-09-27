"""The R2 watcher's probe: what it reports, and that it never goes silent (BACKUP-055 AC1, AC3).

The previous watcher was `echo healthy:1`. It could only fail by not running, so
the alert above it measured the CronJob, not the backups. These tests run the
real `probe.sh` under `sh` against a fake `restic` on PATH and read what it
prints, which is exactly what Vector ships to Loki.

Two properties matter more than any single check:

- **One bad node is never masked.** The fleet line is healthy only if every
  node is, whatever order the nodes are probed in.
- **Every exit path reports.** A restic that crashes, hangs, or a pod started
  without its Secret must still end in `r2_backup_health` `healthy:0`. A probe
  that can exit without a line hands the decision to the rule's 24h noData
  window, a day late.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import time

import shutil

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
PROBE = REPO / "infra/k8s/base/services/r2-backup-watcher/probe.sh"
STAGING = "/opt/node-backup/staging"
PREFIX = "s3:https://example.r2.cloudflarestorage.com/kubelab-backups"

# Stands in for restic. Behaviour per repository comes from files in $FAKE_DIR,
# named after the repository's last path segment:
#   <repo>.fail   exit 1 with that file's text on stderr (no repo, bad password)
#   <repo>.crash  exit 137, as if OOM-killed
#   <repo>.hang   sleep far past any timeout
#   <repo>.snaps  what `snapshots --json` prints (default: one snapshot)
#   <repo>.ls     what `ls latest <dir>` prints
FAKE_RESTIC = r"""#!/bin/sh
repo=""; cmd=""
while [ $# -gt 0 ]; do
  case "$1" in
    -r) repo="$2"; shift ;;
    snapshots|ls) [ -z "$cmd" ] && cmd="$1" ;;
  esac
  shift
done
name="${repo##*/}"
echo "$cmd $name" >> "$FAKE_DIR/calls"
[ -f "$FAKE_DIR/$name.fail" ] && { cat "$FAKE_DIR/$name.fail" >&2; exit 1; }
[ -f "$FAKE_DIR/$name.crash" ] && exit 137
[ -f "$FAKE_DIR/$name.hang" ] && exec sleep 30
case "$cmd" in
  snapshots)
    if [ -f "$FAKE_DIR/$name.snaps" ]; then cat "$FAKE_DIR/$name.snaps"
    else echo '[{"time":"2026-09-26T00:00:00Z","id":"abc","short_id":"abc12345"}]'; fi ;;
  ls) cat "$FAKE_DIR/$name.ls" ;;
esac
"""


def _listing(*services: str, sentinel: bool = True) -> str:
    lines = ["snapshot abc12345 of [/opt/node-backup/staging] at 2026-09-26 00:00:00 filtered by [/opt/node-backup/staging]:"]
    lines += [f"{STAGING}/{s}" for s in services]
    if sentinel:
        lines.append(f"{STAGING}/.capture-complete")
    return "\n".join(lines) + "\n"


# The image runs busybox `sh`, the host usually dash: run every case under both,
# so a bashism or a dash-only behaviour cannot pass here and fail in the pod.
SHELLS = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])


@pytest.fixture(params=SHELLS, ids=lambda s: " ".join(s))
def fleet(tmp_path: pathlib.Path, request):
    """A two-node fleet whose repositories are healthy until a test breaks one."""
    fake = tmp_path / "fake"
    fake.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    restic = bin_dir / "restic"
    restic.write_text(FAKE_RESTIC)
    restic.chmod(0o755)
    targets = tmp_path / "targets.txt"
    targets.write_text(
        "# header comment\n"
        f"rpi3 {PREFIX}/rpi3 uptime_kuma\n"
        f"vps {PREFIX}/kubelab-vps authelia n8n\n"
    )
    (fake / "rpi3.ls").write_text(_listing("uptime_kuma"))
    (fake / "kubelab-vps.ls").write_text(_listing("authelia", "n8n"))
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "WATCHER_TARGETS": str(targets),
        "STAGING_DIR": STAGING,
        "SENTINEL": ".capture-complete",
        "RESTIC_TIMEOUT": "2",
        "RESTIC_PASSWORD": "not-a-real-value-fixture",
        "AWS_ACCESS_KEY_ID": "not-a-real-value-fixture",
        "AWS_SECRET_ACCESS_KEY": "not-a-real-value-fixture",
        "PROBE_SHELL": " ".join(request.param),
    }
    return fake, targets, env


def _run(env: dict[str, str]) -> tuple[int, list[dict], list[dict]]:
    shell = env.get("PROBE_SHELL", "sh").split()
    proc = subprocess.run([*shell, str(PROBE)], env=env, capture_output=True, text=True, timeout=60)
    records = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    nodes = [r for r in records if r["metric"] == "r2_backup_node"]
    fleet_lines = [r for r in records if r["metric"] == "r2_backup_health"]
    assert len(fleet_lines) == 1, f"exactly one fleet line, got {proc.stdout!r} / {proc.stderr!r}"
    assert all(r["namespace"] == "kubelab" for r in records)
    return proc.returncode, nodes, fleet_lines


def _node(nodes: list[dict], name: str) -> dict:
    return next(n for n in nodes if n["node"] == name)


def test_a_healthy_fleet_reports_every_node_and_a_healthy_fleet(fleet) -> None:
    _, _, env = fleet
    rc, nodes, (summary,) = _run(env)
    assert rc == 0
    assert {n["node"] for n in nodes} == {"rpi3", "vps"}
    for n in nodes:
        assert n == {**n, "readable": 1, "snapshots": 1, "missing": [], "sentinel": 1, "healthy": 1}
    assert summary["healthy"] == 1
    assert summary["nodes"] == 2 and summary["unhealthy"] == 0


def test_the_probe_lists_one_directory_not_the_whole_tree(fleet) -> None:
    # A recursive `ls` took 92 s on the Beelink (R3); the probe must not recurse.
    fake, _, env = fleet
    _run(env)
    assert "ls kubelab-vps" in (fake / "calls").read_text()
    proc = subprocess.run(["grep", "-c", "--", "--recursive", str(PROBE)], capture_output=True, text=True)
    assert proc.stdout.strip() == "0"


def test_the_probe_never_takes_a_lock(fleet) -> None:
    # The token is read-only; a locking command fails with PutObject AccessDenied.
    text = PROBE.read_text()
    assert "--no-lock" in text
    for line in text.splitlines():
        if line.strip().startswith("timeout") and "restic" in line:
            assert "--no-lock" in line or "$RESTIC_ARGS" in line or '"$@"' in line, line


@pytest.mark.parametrize(
    ("breakage", "field", "value"),
    [
        ("missing source", "missing", ["n8n"]),
        ("no repository", "readable", 0),
        ("wrong password", "readable", 0),
        ("zero snapshots", "snapshots", 0),
        ("missing sentinel", "sentinel", 0),
        ("restic crashes", "healthy", 0),
        ("restic hangs", "healthy", 0),
    ],
)
def test_each_breakage_fails_its_node_and_the_fleet(fleet, breakage, field, value) -> None:
    fake, _, env = fleet
    vps = "kubelab-vps"
    if breakage == "missing source":
        (fake / f"{vps}.ls").write_text(_listing("authelia"))
    elif breakage == "no repository":
        (fake / f"{vps}.fail").write_text("Fatal: repository does not exist: unable to open config file\n")
    elif breakage == "wrong password":
        (fake / f"{vps}.fail").write_text("Fatal: wrong password or no key found\n")
    elif breakage == "zero snapshots":
        (fake / f"{vps}.snaps").write_text("[]\n")
    elif breakage == "missing sentinel":
        (fake / f"{vps}.ls").write_text(_listing("authelia", "n8n", sentinel=False))
    elif breakage == "restic crashes":
        (fake / f"{vps}.crash").write_text("")
    elif breakage == "restic hangs":
        (fake / f"{vps}.hang").write_text("")

    started = time.monotonic()
    rc, nodes, (summary,) = _run(env)
    assert time.monotonic() - started < 20, "a hanging restic must be cut off by RESTIC_TIMEOUT"

    assert rc != 0
    assert _node(nodes, "vps")[field] == value
    assert _node(nodes, "vps")["healthy"] == 0
    assert _node(nodes, "rpi3")["healthy"] == 1, "one broken node must not fail its neighbours"
    assert summary["healthy"] == 0 and summary["unhealthy"] == 1


def test_a_broken_node_is_not_masked_by_a_healthy_one_after_it(fleet) -> None:
    fake, targets, env = fleet
    # The broken node is probed FIRST and a healthy one last.
    (fake / "rpi3.fail").write_text("Fatal: repository does not exist\n")
    rc, nodes, (summary,) = _run(env)
    assert [n["node"] for n in nodes] == ["rpi3", "vps"]
    assert nodes[-1]["healthy"] == 1
    assert summary["healthy"] == 0


@pytest.mark.parametrize("missing", ["RESTIC_PASSWORD", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"])
def test_a_pod_without_its_secret_still_reports_unhealthy(fleet, missing) -> None:
    _, _, env = fleet
    env = {k: v for k, v in env.items() if k != missing}
    rc, nodes, (summary,) = _run(env)
    assert rc != 0
    assert summary["healthy"] == 0
    assert missing in summary["error"]


def test_missing_targets_still_report_unhealthy(fleet) -> None:
    _, targets, env = fleet
    targets.unlink()
    rc, _, (summary,) = _run(env)
    assert rc != 0 and summary["healthy"] == 0


def test_an_empty_target_list_is_not_a_healthy_fleet(fleet) -> None:
    # Zero nodes checked is zero evidence, not a pass.
    _, targets, env = fleet
    targets.write_text("# only a header\n")
    rc, _, (summary,) = _run(env)
    assert rc != 0 and summary["healthy"] == 0
