"""The R2 watcher's sizing step: what R2 stores, measured by listing (BACKUP-075).

`restic stats --mode raw-data` walks every snapshot's tree, so its cost follows
the snapshot count: on 2026-10-04 the Beelink passed the 600 s budget and every
other node's doubled in three days (`specs/BACKUP-075/verification.md`). It also
measured the wrong quantity, referenced blobs, while R2 bills every object.

`size.sh` runs in the watcher's init container, in the rclone image, and writes
one line per bucket and one per node prefix for the probe to read. These tests
run the real script under `sh` against a fake `rclone` on PATH.

Two properties matter more than any number:

- **It never fails the pod.** An init container that exits non-zero stops the
  health probe from running, and a sizing fault would then silence the backup
  integrity alert. Every failure is a `null` entry and exit 0.
- **A bucket is listed once, at its root.** The fleet's size is what R2 bills,
  which includes objects outside any node's prefix; two nodes sharing a bucket
  must not count it twice.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
SIZE = REPO / "infra/k8s/base/services/r2-backup-watcher/size.sh"
HOST = "example.r2.cloudflarestorage.com"
PREFIX = f"s3:https://{HOST}/kubelab-backups"

# Stands in for `rclone size --json <remote>`. Behaviour per listed path (bucket
# or bucket/prefix, `/` written as `_`) comes from files in $FAKE_DIR:
#   <path>.bytes   the `bytes` the listing reports
#   <path>.fail    exit 1 with that file's text on stderr (AccessDenied, no bucket)
#   <path>.hang    sleep far past any timeout
#   <path>.nobytes exit 0 with JSON that has no `bytes`
# Every call is logged as `size <path> <arguments>`, so a test can read both
# what was listed and how.
FAKE_RCLONE = r"""#!/bin/sh
args="$*"
remote=""
for arg; do case "$arg" in :s3*) remote="$arg" ;; esac; done
path="${remote##*:}"
key="$(printf '%s' "$path" | tr '/' '_')"
echo "size $path $args" >> "$FAKE_DIR/calls"
[ -f "$FAKE_DIR/$key.fail" ] && { cat "$FAKE_DIR/$key.fail" >&2; exit 1; }
[ -f "$FAKE_DIR/$key.hang" ] && exec sleep 30
[ -f "$FAKE_DIR/$key.nobytes" ] && { echo '{"count":3,"sizeless":0}'; exit 0; }
printf '{"count":12,"bytes":%s,"sizeless":0}\n' "$(cat "$FAKE_DIR/$key.bytes")"
"""

BUCKET_BYTES = 600_000_000
NODE_BYTES = {"rpi3": 151_630_989, "kubelab-vps": 77_948_912}

SHELLS = [["sh"]] + ([["busybox", "sh"]] if shutil.which("busybox") else [])


@pytest.fixture(params=SHELLS, ids=lambda s: " ".join(s))
def fleet(tmp_path: pathlib.Path, request):
    """Two nodes in one bucket, every listing answering until a test breaks one."""
    fake = tmp_path / "fake"
    fake.mkdir()
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    rclone = bin_dir / "rclone"
    rclone.write_text(FAKE_RCLONE)
    rclone.chmod(0o755)
    targets = tmp_path / "targets.txt"
    targets.write_text(
        "# header comment\n"
        f"rpi3 {PREFIX}/rpi3 {'1' * 64} 192.0.2.6 22 always-on uptime_kuma\n"
        f"vps {PREFIX}/kubelab-vps {'2' * 64} 192.0.2.2 22 always-on authelia n8n"  # no final newline
    )
    (fake / "kubelab-backups.bytes").write_text(f"{BUCKET_BYTES}\n")
    for prefix, size in NODE_BYTES.items():
        (fake / f"kubelab-backups_{prefix}.bytes").write_text(f"{size}\n")
    out = tmp_path / "sizes" / "sizes.txt"
    out.parent.mkdir()
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "FAKE_DIR": str(fake),
        "WATCHER_TARGETS": str(targets),
        "WATCHER_SIZES": str(out),
        "SIZE_TIMEOUT": "2",
        "AWS_ACCESS_KEY_ID": "not-a-real-value-fixture",
        "AWS_SECRET_ACCESS_KEY": "not-a-real-value-fixture",
    }
    return fake, out, env, request.param


def _run(fleet) -> tuple[subprocess.CompletedProcess, dict[tuple[str, str], list[str]]]:
    _, out, env, shell = fleet
    proc = subprocess.run([*shell, str(SIZE)], env=env, capture_output=True, text=True, timeout=60)
    entries: dict[tuple[str, str], list[str]] = {}
    if out.exists():
        for line in out.read_text().splitlines():
            kind, name, *rest = line.split()
            assert (kind, name) not in entries, f"duplicate entry {kind} {name}"
            entries[(kind, name)] = rest
    return proc, entries


def _calls(fake: pathlib.Path) -> list[str]:
    return (fake / "calls").read_text().splitlines() if (fake / "calls").exists() else []


def test_it_sizes_each_bucket_once_and_each_node_prefix(fleet) -> None:
    fake = fleet[0]
    proc, entries = _run(fleet)
    assert proc.returncode == 0, proc.stderr
    assert entries[("bucket", "kubelab-backups")][0] == str(BUCKET_BYTES)
    assert entries[("node", "rpi3")][0] == str(NODE_BYTES["rpi3"])
    assert entries[("node", "vps")][0] == str(NODE_BYTES["kubelab-vps"])
    listed = [c.split()[1] for c in _calls(fake)]
    assert sorted(listed) == sorted(["kubelab-backups", "kubelab-backups/rpi3", "kubelab-backups/kubelab-vps"])


def test_two_buckets_are_each_listed_once_at_their_root(fleet) -> None:
    """BACKUP-057 PR 4 gives each node its own bucket: each root is listed, none twice."""
    fake, _, env, _ = fleet
    targets = pathlib.Path(env["WATCHER_TARGETS"])
    targets.write_text(
        targets.read_text()
        + f"\nrpi4 s3:https://{HOST}/kubelab-backup-rpi4/rpi4 {'3' * 64} 192.0.2.10 22 on-demand pihole\n"
    )
    (fake / "kubelab-backup-rpi4.bytes").write_text("5000\n")
    (fake / "kubelab-backup-rpi4_rpi4.bytes").write_text("4000\n")
    proc, entries = _run(fleet)
    assert proc.returncode == 0, proc.stderr
    assert entries[("bucket", "kubelab-backups")][0] == str(BUCKET_BYTES)
    assert entries[("bucket", "kubelab-backup-rpi4")][0] == "5000"
    assert entries[("node", "rpi4")][0] == "4000"
    listed = [c.split()[1] for c in _calls(fake)]
    assert sorted(listed) == sorted(
        ["kubelab-backups", "kubelab-backups/rpi3", "kubelab-backups/kubelab-vps", "kubelab-backup-rpi4", "kubelab-backup-rpi4/rpi4"]
    )


def _add_root_node(fleet, marker: str = "bytes", content: str = "7000\n") -> pathlib.Path:
    """A node whose repository is the root of its own bucket, as every node is since BACKUP-057's sitting."""
    fake, _, env, _ = fleet
    targets = pathlib.Path(env["WATCHER_TARGETS"])
    targets.write_text(
        targets.read_text() + f"\nace2 s3:https://{HOST}/kubelab-backup-ace2 {'4' * 64} 192.0.2.5 22 on-demand hermes\n"
    )
    (fake / f"kubelab-backup-ace2.{marker}").write_text(content)
    return fake


def test_a_repository_at_its_bucket_root_is_listed_once(fleet) -> None:
    """#2123: the bucket listing and the node listing cover the same objects, so one serves both."""
    fake = _add_root_node(fleet)
    proc, entries = _run(fleet)
    assert proc.returncode == 0, proc.stderr
    assert entries[("bucket", "kubelab-backup-ace2")][0] == "7000"
    assert entries[("node", "ace2")] == entries[("bucket", "kubelab-backup-ace2")]
    listed = [c.split()[1] for c in _calls(fake)]
    assert listed.count("kubelab-backup-ace2") == 1, listed


def test_a_failed_root_listing_is_null_for_the_node_too(fleet) -> None:
    _add_root_node(fleet, "fail", "AccessDenied: Access Denied\n")
    proc, entries = _run(fleet)
    assert proc.returncode == 0
    assert entries[("bucket", "kubelab-backup-ace2")][0] == "null"
    assert entries[("node", "ace2")][0] == "null"


def test_every_entry_records_how_long_its_listing_took(fleet) -> None:
    """The duration is AC3's evidence that the cost no longer follows the snapshot count."""
    _, entries = _run(fleet)
    assert len(entries) == 3, entries
    for rest in entries.values():
        assert len(rest) == 2 and rest[1].isdigit(), rest


def test_it_reaches_r2_by_the_targets_endpoint_with_no_config_file(fleet) -> None:
    """Configured entirely on the command line: the token comes from AWS_*, the endpoint from the target.

    `no_check_bucket`: the token is read-only, and rclone otherwise tries to create the bucket.
    """
    fake = fleet[0]
    _run(fleet)
    assert len(_calls(fake)) == 3, "no call, no option checked"
    for call in _calls(fake):
        assert "--json" in call and "--fast-list" in call, call
        remote = next(a for a in call.split() if a.startswith(":s3"))
        for option in ("provider=Cloudflare", "env_auth=true", "no_check_bucket=true", f"endpoint='https://{HOST}'"):
            assert option in remote, (option, remote)


@pytest.mark.parametrize("marker", ["fail", "nobytes"])
def test_a_failed_node_listing_is_null_and_never_fails_the_pod(fleet, marker) -> None:
    fake = fleet[0]
    (fake / f"kubelab-backups_kubelab-vps.{marker}").write_text("AccessDenied: Access Denied\n")
    proc, entries = _run(fleet)
    assert proc.returncode == 0
    assert entries[("node", "vps")][0] == "null"
    assert entries[("node", "rpi3")][0] == str(NODE_BYTES["rpi3"])
    assert entries[("bucket", "kubelab-backups")][0] == str(BUCKET_BYTES)
    assert "r2-backup-watcher: vps: size unknown:" in proc.stderr


def test_a_failed_bucket_listing_is_null(fleet) -> None:
    fake = fleet[0]
    (fake / "kubelab-backups.fail").write_text("AccessDenied: Access Denied\n")
    proc, entries = _run(fleet)
    assert proc.returncode == 0
    assert entries[("bucket", "kubelab-backups")][0] == "null"
    assert "AccessDenied" in proc.stderr


def test_a_hung_listing_is_cut_off_and_null(fleet) -> None:
    fake = fleet[0]
    (fake / "kubelab-backups_rpi3.hang").write_text("")
    started = time.monotonic()
    proc, entries = _run(fleet)
    assert time.monotonic() - started < 15, "SIZE_TIMEOUT must bound every listing"
    assert proc.returncode == 0
    assert entries[("node", "rpi3")][0] == "null"
    assert entries[("node", "vps")][0] == str(NODE_BYTES["kubelab-vps"])


def test_without_credentials_it_writes_nulls_and_exits_zero(fleet) -> None:
    fake, _, env, _ = fleet
    for var in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"):
        env.pop(var)
    proc, entries = _run(fleet)
    assert proc.returncode == 0
    assert not _calls(fake)
    assert entries and all(rest[0] == "null" for rest in entries.values())
    assert "missing env AWS_ACCESS_KEY_ID" in proc.stderr


def test_an_unreadable_targets_file_still_exits_zero(fleet) -> None:
    _, out, env, _ = fleet
    env["WATCHER_TARGETS"] = str(out.parent / "absent.txt")
    proc, _ = _run(fleet)
    assert proc.returncode == 0
    assert "targets file" in proc.stderr
