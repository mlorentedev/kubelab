"""The prune script, executed (BACKUP-057 Q6, amended 2026-10-03).

`forget --prune` left the ship for a unit of its own. Under the bucket lock a
refused DELETE holds restic in retries for about 15 minutes, longer than the
ship's timeout, so a prune in the ship would turn a harmless refusal into a
killed backup. The prune unit fails, and notifies, on restic's exit code
alone: a refused pack exits 0 (expected, harmless), a refused snapshot exits 3
(cannot happen while `--keep-within` exceeds R, so it is a real fault).

These tests RUN the rendered `node-backup-prune.sh` under bash against a fake
restic and assert on the calls it makes and the code it exits with.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.test_node_backup_role import _defaults, _render

# Stands in for restic. `unlock.rc` and `forget.rc` in $FAKE_DIR set the exit
# codes (default 0). Every call is appended to `calls` with its arguments, the
# global `--repo` and `--stuck-request-timeout` stripped.
FAKE_RESTIC = r"""#!/bin/bash
while [ $# -gt 0 ]; do
  case "$1" in
    --repo|--stuck-request-timeout) shift 2 ;;
    *) break ;;
  esac
done
echo "$*" >> "$FAKE_DIR/calls"
case "$1" in
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

    def run(*, shipped: bool = True, unlock_rc: int = 0, forget_rc: int = 0):
        if shipped:
            marker.write_text("a" * 64 + "\n")
        (fake_dir / "unlock.rc").write_text(f"{unlock_rc}\n")
        (fake_dir / "forget.rc").write_text(f"{forget_rc}\n")
        env = {"PATH": os.environ["PATH"], "FAKE_DIR": str(fake_dir)}
        proc = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
        calls_file = fake_dir / "calls"
        calls = calls_file.read_text().splitlines() if calls_file.exists() else []
        return proc, calls

    return run


def test_it_unlocks_then_forgets_with_the_retention_flags_and_its_bounds(prune) -> None:
    """Exactly two calls, in this order. `unlock` first, because restic 0.19.1
    never skips a stale lock (`checkForOtherLocks` does not test `Stale()`), so a
    killed prune would otherwise block every later run."""
    defaults = _defaults()
    proc, calls = prune()
    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "unlock",
        f"forget {defaults['node_backup_retention_flags']} --prune --retry-lock 10m"
        f" -o s3.connections={defaults['node_backup_prune_connections']}",
    ]


@pytest.mark.parametrize("rc", [0, 3, 1])
def test_the_unit_gets_restic_s_exit_code(prune, rc: int) -> None:
    """0 is a clean prune or a refused pack (harmless); 3 is a refused snapshot
    (a real fault); anything non-zero fails the unit, and `OnFailure=` notifies."""
    proc, _calls = prune(forget_rc=rc)
    assert proc.returncode == rc


def test_a_failed_unlock_fails_before_forget(prune) -> None:
    proc, calls = prune(unlock_rc=1)
    assert proc.returncode != 0
    assert calls == ["unlock"]


def test_a_node_that_has_never_shipped_prunes_nothing_and_pages_nothing(prune) -> None:
    """`Persistent=true` fires the timer at boot, possibly before the first ship
    has created the repository. That is not a fault, so it must not notify."""
    proc, calls = prune(shipped=False)
    assert proc.returncode == 0
    assert calls == []
    assert "not shipped" in proc.stdout
