"""The prune script, executed (BACKUP-057 Q6, amended 2026-10-03).

`forget --prune` left the ship for a unit of its own. Under the bucket lock a
refused DELETE holds restic in retries for about 15 minutes, longer than the
ship's timeout, so a prune in the ship would turn a harmless refusal into a
killed backup. The prune unit fails, and notifies, on restic's exit code
alone: a refused pack exits 0 (expected, harmless), a refused snapshot exits 3
(cannot happen while `--keep-within` exceeds R, so it is a real fault).

Copied history is the exception (#1920). A snapshot `restic copy` brought in at
the migration to the node's own bucket keeps its own time, but its objects were
written at the copy, and the lock ages objects. So for R days after the copy,
`forget` asks to delete snapshots the lock still refuses, and exits 3 every day.
The script waits instead, until the oldest snapshot written here is older than R.

These tests RUN the rendered `node-backup-prune.sh` under bash against a fake
restic and assert on the calls it makes and the code it exits with.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from tests.test_node_backup_role import _common, _defaults, _plays, _render

LOCK_DAYS = int(_common()["backup"]["r2"]["lock_retention_days"])

# Stands in for restic. `snapshots.rc`, `unlock.rc` and `forget.rc` in $FAKE_DIR
# set the exit codes (default 0), and `snapshots` prints `snapshots.json` (an
# empty list by default). Every call is appended to `calls` with its arguments,
# the global `--repo` and `--stuck-request-timeout` stripped.
FAKE_RESTIC = r"""#!/bin/bash
while [ $# -gt 0 ]; do
  case "$1" in
    --repo|--stuck-request-timeout) shift 2 ;;
    *) break ;;
  esac
done
echo "$*" >> "$FAKE_DIR/calls"
case "$1" in
  snapshots)
    cat "$FAKE_DIR/snapshots.json" 2>/dev/null || echo '[]'
    exit "$(cat "$FAKE_DIR/snapshots.rc" 2>/dev/null || echo 0)" ;;
  unlock) exit "$(cat "$FAKE_DIR/unlock.rc" 2>/dev/null || echo 0)" ;;
  forget) exit "$(cat "$FAKE_DIR/forget.rc" 2>/dev/null || echo 0)" ;;
esac
exit 0
"""


@pytest.fixture
def prune(tmp_path: Path):
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    restic = tmp_path / "restic"
    restic.write_text(FAKE_RESTIC)
    restic.chmod(0o755)
    creds = {}
    for name in ("password", "access", "secret"):
        creds[name] = tmp_path / f"cred-{name}"
        creds[name].write_text("dummy\n")
    marker = tmp_path / "r2.repository-id"
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    script = tmp_path / "prune.sh"
    script.write_text(
        _render(
            "node-backup-prune.sh.j2",
            node_backup_r2_repository="s3:https://acct.r2.cloudflarestorage.com/kubelab-backup-beelink",
            node_backup_restic_install_path=str(restic),
            node_backup_restic_password_file=str(creds["password"]),
            node_backup_r2_access_key_file=str(creds["access"]),
            node_backup_r2_secret_key_file=str(creds["secret"]),
            node_backup_r2_repository_id_file=str(marker),
        )
    )

    def run(
        *,
        shipped: bool = True,
        snapshots: list[dict] | None = None,
        snapshots_rc: int = 0,
        unlock_rc: int = 0,
        forget_rc: int = 0,
    ):
        if shipped:
            marker.write_text("a" * 64 + "\n")
        (fake_dir / "snapshots.json").write_text(json.dumps(snapshots or []))
        (fake_dir / "snapshots.rc").write_text(f"{snapshots_rc}\n")
        (fake_dir / "unlock.rc").write_text(f"{unlock_rc}\n")
        (fake_dir / "forget.rc").write_text(f"{forget_rc}\n")
        env = {"PATH": os.environ["PATH"], "FAKE_DIR": str(fake_dir), "TMPDIR": str(scratch)}
        proc = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
        calls_file = fake_dir / "calls"
        calls = calls_file.read_text().splitlines() if calls_file.exists() else []
        return proc, calls

    run.scratch = scratch
    return run


LISTING = "snapshots -q --json --no-lock"


def _forget_call() -> str:
    defaults = _defaults()
    return (
        f"forget {defaults['node_backup_retention_flags']} --prune --retry-lock 10m"
        f" -o s3.connections={defaults['node_backup_prune_connections']}"
    )


def _snapshot(days_old: float, *, copied: bool = False) -> dict:
    """A snapshot as `restic snapshots --json` prints it: local offset, nanoseconds."""
    when = (datetime.now(timezone.utc) - timedelta(days=days_old)).astimezone(timezone(timedelta(hours=-6)))
    snap = {"id": os.urandom(32).hex(), "time": when.strftime("%Y-%m-%dT%H:%M:%S.123456789-06:00")}
    if copied:
        snap["original"] = os.urandom(32).hex()
    return snap


def test_it_lists_then_unlocks_then_forgets_with_the_retention_flags_and_its_bounds(prune) -> None:
    """Exactly three calls, in this order. The listing first and lock-free, like the
    ship's probe, so a stale lock cannot fail it. `unlock` before `forget`, because
    restic 0.19.1 never skips a stale lock (`checkForOtherLocks` does not test
    `Stale()`), so a killed prune would otherwise block every later run."""
    proc, calls = prune(snapshots=[_snapshot(40), _snapshot(1)])
    assert proc.returncode == 0, proc.stderr
    assert calls == [LISTING, "unlock", _forget_call()]


def test_a_repository_whose_own_history_is_younger_than_the_lock_waits_for_its_copies(prune) -> None:
    """#1920: forget would ask to delete copies the lock refuses, exit 3, and page."""
    copies = [_snapshot(90, copied=True), _snapshot(60, copied=True)]
    proc, calls = prune(snapshots=[*copies, _snapshot(LOCK_DAYS - 1), _snapshot(1)])
    assert proc.returncode == 0, proc.stderr
    assert calls == [LISTING]
    assert "copied" in proc.stdout


def test_copies_stop_holding_forget_once_the_oldest_own_snapshot_is_older_than_the_lock(prune) -> None:
    """The migration copies before the node's first ship here, so an own snapshot
    older than R means everything copied is older than R as objects too."""
    copies = [_snapshot(90, copied=True), _snapshot(60, copied=True)]
    proc, calls = prune(snapshots=[*copies, _snapshot(LOCK_DAYS + 1), _snapshot(1)])
    assert proc.returncode == 0, proc.stderr
    assert calls == [LISTING, "unlock", _forget_call()]


def test_copies_with_no_own_snapshot_wait(prune) -> None:
    """Nothing written here yet says nothing about when the copy happened."""
    proc, calls = prune(snapshots=[_snapshot(90, copied=True)])
    assert proc.returncode == 0, proc.stderr
    assert calls == [LISTING]


def test_a_repository_with_no_copies_is_not_held_by_its_age(prune) -> None:
    """A node that started here has nothing the lock ages differently: forget runs
    whatever its age, and removes nothing younger than --keep-within anyway."""
    proc, calls = prune(snapshots=[_snapshot(2), _snapshot(1)])
    assert proc.returncode == 0, proc.stderr
    assert calls == [LISTING, "unlock", _forget_call()]


@pytest.mark.parametrize("days_old", [1, LOCK_DAYS + 1])
def test_the_listing_leaves_nothing_behind(prune, days_old: int) -> None:
    """The script ends in `exec`, which skips the EXIT trap, so the listing is
    removed by hand on that path as well as by the trap on the others."""
    proc, _calls = prune(snapshots=[_snapshot(90, copied=True), _snapshot(days_old)])
    assert proc.returncode == 0, proc.stderr
    assert list(prune.scratch.iterdir()) == []


@pytest.mark.parametrize("rc", [1, 12])
def test_a_repository_that_cannot_be_listed_fails_the_unit(prune, rc: int) -> None:
    """A listing that fails is a fault worth a page, never a reason to skip quietly."""
    proc, calls = prune(snapshots_rc=rc)
    assert proc.returncode == rc
    assert calls == [LISTING]


@pytest.mark.parametrize("rc", [0, 3, 1])
def test_the_unit_gets_restic_s_exit_code(prune, rc: int) -> None:
    """0 is a clean prune or a refused pack (harmless); 3 is a refused snapshot
    (a real fault); anything non-zero fails the unit, and `OnFailure=` notifies."""
    proc, _calls = prune(forget_rc=rc)
    assert proc.returncode == rc


def test_a_failed_unlock_fails_before_forget(prune) -> None:
    proc, calls = prune(unlock_rc=1)
    assert proc.returncode != 0
    assert calls == [LISTING, "unlock"]


def test_a_node_that_has_never_shipped_prunes_nothing_and_pages_nothing(prune) -> None:
    """`Persistent=true` fires the timer at boot, possibly before the first ship
    has created the repository. That is not a fault, so it must not notify."""
    proc, calls = prune(shipped=False)
    assert proc.returncode == 0
    assert calls == []
    assert "not shipped" in proc.stdout


def test_the_playbook_supplies_r_from_the_ssot_and_the_role_does_not_guess_it() -> None:
    assert "node_backup_r2_lock_retention_days" not in _defaults()
    for play in _plays():
        role = next(r for r in play["roles"] if str(r.get("role", "")).endswith("/node_backup"))
        assert role["vars"]["node_backup_r2_lock_retention_days"] == "{{ config.backup.r2.lock_retention_days }}"
