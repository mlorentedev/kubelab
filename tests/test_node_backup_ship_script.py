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
fleet's restic 0.19.1 on 2026-09-30 (specs/archive/BACKUP-058-no-silent-reinit).
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
#   snapshots.rc  exit code of `snapshots` (default 0), or a behaviour:
#                 `refuse` retries a rejected request forever, printing restic's
#                 retry line each time (R2's answer to a bad credential, #1939);
#                 `silent` hangs and prints nothing (an unreachable endpoint);
#                 `unavailable` retries a 503 forever (R2 down, not the credential)
#   id            the repository id `cat config` reports
#   forget.rc     exit code of `forget` (default 0)
#   check.rc      exit code of `check` (default 0)
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
    if [ "$rc" = refuse ]; then
      while :; do
        echo "Stat(<config/>) returned error, retrying after 875.524205ms: Stat: Unauthorized" >&2
        sleep 0.2
      done
    fi
    if [ "$rc" = unavailable ]; then
      while :; do
        echo "Stat(<config/>) returned error, retrying after 1.2s: Stat: 503 Service Unavailable" >&2
        sleep 0.2
      done
    fi
    [ "$rc" = silent ] && exec sleep 60
    [ "$rc" = 10 ] && echo "Fatal: repository does not exist: unable to open config file" >&2
    [ "$rc" = 1 ] && echo "Fatal: unable to open repository: connection reset" >&2
    exit "$rc" ;;
  init)
    echo "$NEW_ID" > "$FAKE_DIR/id"
    echo 0 > "$FAKE_DIR/snapshots.rc" ;;
  forget)
    exit "$(cat "$FAKE_DIR/forget.rc" 2>/dev/null || echo 0)" ;;
  check)
    exit "$(cat "$FAKE_DIR/check.rc" 2>/dev/null || echo 0)" ;;
  cat)
    printf '{\n  "version": 2,\n  "id": "%s",\n  "chunker_polynomial": "3dea92648f6e83"\n}\n' "$(cat "$FAKE_DIR/id")" ;;
esac
exit 0
"""


# Stands in for `date` when a test fixes the clock: `+%s` answers $FAKE_NOW, and
# anything else goes to the real date, so the script's other timestamps work.
FAKE_DATE = r"""#!/bin/bash
if [ "$*" = "+%s" ] && [ -n "${FAKE_NOW:-}" ]; then echo "$FAKE_NOW"; exit 0; fi
exec /bin/date "$@"
"""

WEEK = 604800
READ_DATA_GROUPS = 4


@pytest.fixture
def node(tmp_path: Path):
    """A rendered ship script wired entirely into tmp_path, and a runner for it."""
    fake_dir = tmp_path / "fake"
    fake_dir.mkdir()
    restic = tmp_path / "restic"
    restic.write_text(FAKE_RESTIC)
    restic.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "date").write_text(FAKE_DATE)
    (bin_dir / "date").chmod(0o755)

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
            # Seconds, not the role's 120: the refusal tests wait it out.
            node_backup_probe_timeout=2,
            node_backup_check_read_data_groups=READ_DATA_GROUPS,
        )
    )

    def run(
        *,
        snapshots_rc: int | str,
        repo_id: str = EXISTING_ID,
        recorded: str | None = None,
        forget_rc: int = 0,
        check: bool = False,
        check_rc: int = 0,
        now: int | None = None,
    ):
        (fake_dir / "snapshots.rc").write_text(f"{snapshots_rc}\n")
        (fake_dir / "forget.rc").write_text(f"{forget_rc}\n")
        (fake_dir / "check.rc").write_text(f"{check_rc}\n")
        (fake_dir / "id").write_text(f"{repo_id}\n")
        calls_file = fake_dir / "calls"
        earlier = len(calls_file.read_text().splitlines()) if calls_file.exists() else 0
        if recorded is not None:
            marker.write_text(f"{recorded}\n")
        env = {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_DIR": str(fake_dir), "NEW_ID": NEW_ID}
        if now is not None:
            env["FAKE_NOW"] = str(now)
        argv = ["bash", str(script)] + (["--check"] if check else [])
        proc = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30)
        calls = (fake_dir / "calls").read_text().splitlines() if (fake_dir / "calls").exists() else []
        # `verbs` accumulates across runs (a test may assert on a sequence);
        # `run.calls` holds this run's calls only.
        run.calls = calls[earlier:]
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


def test_a_marker_that_is_a_dangling_symlink_is_refused_with_the_override(node, tmp_path) -> None:
    """`-e` is false for a symlink whose target is gone, so it is checked with `-L`.

    Read as absent, it would reopen `init`. Read with a bare `tr <`, it would
    abort on `set -e` with no word about the marker or the way out.
    """
    marker = tmp_path / "state" / "r2.repository-id"
    marker.symlink_to(tmp_path / "gone")
    proc, verbs, _ = node(snapshots_rc=10)
    assert proc.returncode != 0
    assert "init" not in verbs
    assert "backup" not in verbs
    assert str(marker) in proc.stderr
    assert "make backup-repo-reinit" in proc.stderr


def test_a_rejected_credential_is_named_within_the_probe_timeout(node) -> None:
    """R2 answers a bad credential with 401 `Unauthorized`, and restic retries it.

    restic 0.19.1's S3 backend treats only `AccessDenied` and `InvalidRange` as
    permanent, and its retry budget is 15 minutes, longer than the unit's 600 s.
    `--stuck-request-timeout` does not apply: these requests fail, they do not
    stall. So the probe carries its own bound and names the last refusal
    (measured 2026-09-30, #1939).
    """
    proc, verbs, marker = node(snapshots_rc="refuse")
    assert proc.returncode != 0
    assert "init" not in verbs and "backup" not in verbs
    assert _marker_value(marker) is None
    # restic's own lines still reach the journal, and the verdict names them.
    assert "returned error, retrying" in proc.stderr
    verdict = [line for line in proc.stderr.splitlines() if line.startswith("node-backup-ship:")]
    assert verdict and "Stat: Unauthorized" in verdict[-1], proc.stderr
    assert "credential" in proc.stderr


def test_an_endpoint_that_never_answers_is_reported_as_such(node) -> None:
    proc, verbs, marker = node(snapshots_rc="silent")
    assert proc.returncode != 0
    assert "init" not in verbs and "backup" not in verbs
    assert "no answer from r2" in proc.stderr.lower(), proc.stderr
    assert "credential" not in proc.stderr


def test_a_retried_outage_is_reported_as_the_error_it_is_not_as_a_refusal(node) -> None:
    """A 503 is retried just like a 401, so the probe times out on both.

    Only the last retry line tells them apart. The verdict must quote it without
    calling it a refusal, and must not point at the credential.
    """
    proc, verbs, _ = node(snapshots_rc="unavailable")
    assert proc.returncode != 0
    assert "init" not in verbs and "backup" not in verbs
    verdict = [line for line in proc.stderr.splitlines() if line.startswith("node-backup-ship:")]
    assert verdict and "503 Service Unavailable" in verdict[-1], proc.stderr
    assert "refused" not in verdict[-1], verdict[-1]
    assert "credential" not in proc.stderr


def test_the_probe_timeout_sits_between_one_stuck_request_and_the_unit() -> None:
    """Above one stuck request, so a slow link still answers. Below the unit, so the verdict is logged.

    The probe also leaves the unit room for the backup itself.
    """
    import re

    import yaml

    role = Path(__file__).resolve().parents[1] / "infra" / "ansible" / "roles" / "node_backup"
    defaults = yaml.safe_load((role / "defaults" / "main.yml").read_text())
    stuck = int(str(defaults["node_backup_stuck_request_timeout"]).rstrip("s"))
    probe = int(defaults["node_backup_probe_timeout"])
    unit = re.search(r"^TimeoutStartSec=(\d+)$", (role / "templates" / "node-backup-ship.service.j2").read_text(), re.M)
    assert unit, "the ship unit declares no TimeoutStartSec"
    assert stuck < probe <= int(unit.group(1)) // 4


def _check_call(calls: list[str]) -> str:
    [call] = [c for c in calls if c.split()[0] == "check"]
    return call


def test_the_weekly_check_reads_a_group_of_pack_data(node) -> None:
    proc, verbs, _ = node(snapshots_rc=0, recorded=EXISTING_ID, check=True, now=0)
    assert proc.returncode == 0, proc.stderr
    assert _check_call(node.calls) == f"check --read-data-subset 1/{READ_DATA_GROUPS}"
    assert f"reading pack group 1/{READ_DATA_GROUPS}" in proc.stdout


def test_the_read_data_rotation_reads_every_group_once_per_cycle(node) -> None:
    """Every pack is read within t weeks: t consecutive weeks read each group exactly once."""
    groups = []
    for week in range(READ_DATA_GROUPS):
        node(snapshots_rc=0, recorded=EXISTING_ID, check=True, now=week * WEEK + 3600)
        groups.append(_check_call(node.calls).split()[-1])
    assert sorted(groups) == [f"{n}/{READ_DATA_GROUPS}" for n in range(1, READ_DATA_GROUPS + 1)]


def test_the_read_data_rotation_is_continuous_across_a_year_boundary(node) -> None:
    """ISO weeks wrap 52/53 -> 1 and would skip or repeat a group there; epoch weeks do not."""
    new_year_2027 = 1798761600  # 2027-01-01T00:00:00Z, which falls in ISO week 53 of 2026
    before, after = [], []
    for offset in (-WEEK, 0, WEEK):
        node(snapshots_rc=0, recorded=EXISTING_ID, check=True, now=new_year_2027 + offset)
        n = int(_check_call(node.calls).split()[-1].split("/")[0])
        (before if offset < 0 else after).append(n)
    sequence = before + after
    assert [(b - a) % READ_DATA_GROUPS for a, b in zip(sequence, sequence[1:])] == [1, 1]


def test_the_frequent_ship_does_not_check(node) -> None:
    proc, verbs, _ = node(snapshots_rc=0, recorded=EXISTING_ID, check=False, now=0)
    assert proc.returncode == 0, proc.stderr
    assert "check" not in verbs


def test_a_failed_check_fails_the_run(node) -> None:
    """A pack that cannot be read back must fail the unit, which is what pages (OnFailure)."""
    proc, verbs, _ = node(snapshots_rc=0, recorded=EXISTING_ID, check=True, check_rc=1, now=0)
    assert proc.returncode != 0
    assert "check" in verbs
    assert "ship complete" not in proc.stdout
