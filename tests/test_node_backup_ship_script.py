"""The ship script, executed: when it may create a repository (BACKUP-058).

`tests/test_node_backup_role.py` renders the role's templates and reads them.
These tests go one step further: they RUN the rendered `node-backup-ship.sh`
under bash against a fake restic, because the property that matters here is
behavioural. The script used to run `restic init` whenever `restic snapshots`
failed, for any reason, so a deleted repository came back as a fresh one with
one snapshot and every earlier restore point was gone without a page.

The contract, per destination marker `<dir>/r2.repository-id`:

- first ship (exit 10, no marker): init, ship, record the new repository id;
- adoption (exit 0, no marker): an existing repository is recorded, never
  re-initialised; this is how the four live nodes pick the marker up;
- marker present and exit 10: the history is gone. Fail, never init;
- marker present and a different id: the repository was replaced. Fail
  before `backup` writes a snapshot into it;
- any other exit code (a transient or credential error): fail, never init.

Exit 10 is restic's "repository does not exist", measured against R2 with the
fleet's restic 0.19.1 on 2026-09-30 (specs/BACKUP-058-no-silent-reinit).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from tests.test_node_backup_role import _render

EXISTING_ID = "a" * 64
NEW_ID = "b" * 64

# Stands in for restic. State lives in $FAKE_DIR:
#   snapshots.rc  exit code of `snapshots` (default 0)
#   id            the repository id `cat config` reports
#   forget.rc     exit code of `forget` (default 0)
# `init` sets a new id and makes `snapshots` succeed, as a real init would.
# Every subcommand is appended to `calls`, which is what the tests assert on.
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
    rc="$(cat "$FAKE_DIR/snapshots.rc" 2>/dev/null || echo 0)"
    [ "$rc" = 10 ] && echo "Fatal: repository does not exist: unable to open config file" >&2
    [ "$rc" = 1 ] && echo "Fatal: unable to open repository: connection reset" >&2
    exit "$rc" ;;
  init)
    echo "$NEW_ID" > "$FAKE_DIR/id"
    echo 0 > "$FAKE_DIR/snapshots.rc" ;;
  forget)
    exit "$(cat "$FAKE_DIR/forget.rc" 2>/dev/null || echo 0)" ;;
  cat)
    printf '{\n  "version": 2,\n  "id": "%s",\n  "chunker_polynomial": "3dea92648f6e83"\n}\n' "$(cat "$FAKE_DIR/id")" ;;
esac
exit 0
"""


@pytest.fixture
def node(tmp_path: Path):
    """A rendered ship script wired entirely into tmp_path, and a runner for it."""
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    restic = tmp_path / "restic"
    restic.write_text(FAKE_RESTIC)
    restic.chmod(0o755)

    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "gitea").mkdir()
    sentinel = staging / ".capture-complete"
    sentinel.touch()

    creds = {}
    for name in ("password", "access", "secret"):
        creds[name] = tmp_path / f"cred-{name}"
        creds[name].write_text("dummy\n")

    state = tmp_path / "state"
    state.mkdir()
    marker = state / "r2.repository-id"

    script = tmp_path / "ship.sh"
    script.write_text(
        _render(
            "node-backup-ship.sh.j2",
            # Derived defaults are raw Jinja strings in `_defaults()` (nothing
            # expands them outside Ansible), so every one the script uses is
            # passed as the value Ansible would have produced.
            node_backup_r2_repository="s3:https://acct.r2.cloudflarestorage.com/kubelab-backups/beelink",
            node_backup_restic_install_path=str(restic),
            node_backup_staging_dir=str(staging),
            node_backup_capture_sentinel=str(sentinel),
            node_backup_restic_password_file=str(creds["password"]),
            node_backup_r2_access_key_file=str(creds["access"]),
            node_backup_r2_secret_key_file=str(creds["secret"]),
            node_backup_heartbeat_token_file=str(tmp_path / "no-heartbeat-token"),
            node_backup_repository_id_dir=str(state),
            node_backup_r2_repository_id_file=str(marker),
        )
    )

    def run(*, snapshots_rc: int, repo_id: str = EXISTING_ID, recorded: str | None = None, forget_rc: int = 0):
        (fake_dir / "snapshots.rc").write_text(f"{snapshots_rc}\n")
        (fake_dir / "forget.rc").write_text(f"{forget_rc}\n")
        (fake_dir / "id").write_text(f"{repo_id}\n")
        if recorded is not None:
            marker.write_text(f"{recorded}\n")
        env = {"PATH": os.environ["PATH"], "FAKE_DIR": str(fake_dir), "NEW_ID": NEW_ID}
        proc = subprocess.run(["bash", str(script)], env=env, capture_output=True, text=True, timeout=30)
        calls = (fake_dir / "calls").read_text().splitlines() if (fake_dir / "calls").exists() else []
        verbs = [c.split()[0] for c in calls]
        return proc, verbs, marker

    return run


def _marker_value(marker: Path) -> str | None:
    return marker.read_text().strip() if marker.exists() else None


def test_first_ship_initialises_and_records_the_new_repository(node) -> None:
    proc, verbs, marker = node(snapshots_rc=10)
    assert proc.returncode == 0, proc.stderr
    assert verbs.count("init") == 1
    assert "backup" in verbs
    assert _marker_value(marker) == NEW_ID


def test_an_existing_repository_is_adopted_without_init(node) -> None:
    proc, verbs, marker = node(snapshots_rc=0)
    assert proc.returncode == 0, proc.stderr
    assert "init" not in verbs
    assert _marker_value(marker) == EXISTING_ID


def test_a_recorded_repository_that_matches_ships_normally(node) -> None:
    proc, verbs, marker = node(snapshots_rc=0, recorded=EXISTING_ID)
    assert proc.returncode == 0, proc.stderr
    assert "init" not in verbs
    assert "backup" in verbs
    assert _marker_value(marker) == EXISTING_ID


def test_a_transient_error_fails_without_init(node) -> None:
    proc, verbs, marker = node(snapshots_rc=1)
    assert proc.returncode != 0
    assert "init" not in verbs
    assert "backup" not in verbs
    assert _marker_value(marker) is None


def test_a_repository_gone_after_prior_ships_fails_loudly_without_init(node) -> None:
    proc, verbs, marker = node(snapshots_rc=10, recorded=EXISTING_ID)
    assert proc.returncode != 0
    assert "init" not in verbs
    assert "backup" not in verbs
    assert _marker_value(marker) == EXISTING_ID
    assert "r2" in proc.stderr
    assert EXISTING_ID in proc.stderr
    assert "make backup-repo-reinit" in proc.stderr


def test_a_replaced_repository_fails_before_writing_a_snapshot(node) -> None:
    proc, verbs, marker = node(snapshots_rc=0, repo_id=NEW_ID, recorded=EXISTING_ID)
    assert proc.returncode != 0
    assert "init" not in verbs
    assert "backup" not in verbs
    assert _marker_value(marker) == EXISTING_ID
    assert EXISTING_ID in proc.stderr and NEW_ID in proc.stderr
    assert "make backup-repo-reinit" in proc.stderr


def test_the_repository_is_recorded_once_a_snapshot_exists_even_if_retention_fails(node) -> None:
    """The history exists from the first successful `backup`, not from the end of the run.

    Recording only after `forget` and `check` left a window: a first ship whose
    retention failed held a snapshot with no marker, so a deletion before the
    next whole run would have been re-initialised silently. The run still
    fails, because a failed retention is a failed ship.
    """
    proc, verbs, marker = node(snapshots_rc=10, forget_rc=1)
    assert proc.returncode != 0
    assert "backup" in verbs
    assert _marker_value(marker) == NEW_ID
    # And the protection holds from there: the repository vanishing is refused.
    proc, verbs, marker = node(snapshots_rc=10)
    assert proc.returncode != 0
    assert verbs.count("init") == 1, "the second run must not initialise"


def test_no_temporary_marker_is_left_behind(node) -> None:
    # Concurrent ships (the frequent and weekly units) must not share one
    # predictable temp path, and a whole run leaves only the marker.
    proc, _, marker = node(snapshots_rc=0)
    assert proc.returncode == 0, proc.stderr
    assert [p.name for p in marker.parent.iterdir()] == [marker.name]


@pytest.mark.parametrize("snapshots_rc", [0, 10])
@pytest.mark.parametrize("recorded", ["", "   ", "not-a-repository-id"], ids=["empty", "blank", "garbage"])
def test_a_marker_that_exists_without_an_id_is_refused_not_treated_as_absent(node, recorded, snapshots_rc) -> None:
    """A present marker means "this node has shipped here", whatever it holds.

    Reading it as absent when it is empty made `init` reachable again: with the
    repository gone (exit 10), a truncated marker re-initialised it silently,
    which is the defect this spec removes. No committed path writes a blank
    marker (the write is atomic), so the ways in are external: a `touch`, a
    restore tool that truncates. Found by the spec's adversarial review.
    """
    proc, verbs, marker = node(snapshots_rc=snapshots_rc, recorded=recorded)
    assert proc.returncode != 0
    assert "init" not in verbs
    assert "backup" not in verbs
    assert _marker_value(marker) == recorded.strip()
    assert str(marker) in proc.stderr
    assert "make backup-repo-reinit" in proc.stderr


def test_the_override_printed_on_a_refusal_runs_as_pasted(node) -> None:
    """The refusal names the env the pipeline was deployed for, never a placeholder."""
    proc, _, _ = node(snapshots_rc=10, recorded=EXISTING_ID)
    assert "make backup-repo-reinit NODE=beelink DEST=r2 ENV=prod" in proc.stderr
    assert "<env>" not in proc.stderr
