"""`make backup-drill-postgres` proves the dump in R2 restores completely (BACKUP-046 AC5).

"Restores completely" and not "equals live": the snapshot is up to four hours
older than live, and the board keeps being written, so equal counts would fail
on every busy afternoon and pass nothing extra. What a broken backup looks like
is a missing database, a missing table, or a table that came back empty, and
those are what fail.

The dump holds role password hashes and every row of the board. Nothing here
may print a row: only names and counts leave the drill.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from toolkit.features.postgres_drill import TRAILER, compare, parse_counts, run_drill

SECRET = "ROW-CONTENT-THAT-MUST-NOT-PRINT"


def test_counts_parse_from_psql_unaligned_output() -> None:
    assert parse_counts("public.tasks|12\npublic.users|0\n") == {"public.tasks": 12, "public.users": 0}


def test_a_complete_restore_passes_even_when_live_has_moved_on() -> None:
    live = {"vikunja": {"public.tasks": 120, "public.users": 2}}
    restored = {"vikunja": {"public.tasks": 117, "public.users": 2}}
    ok, lines = compare(live, restored)
    assert ok
    assert any("public.tasks" in line and "117" in line and "120" in line for line in lines)


@pytest.mark.parametrize(
    ("restored", "named"),
    [
        ({}, "vikunja"),
        ({"vikunja": {"public.users": 2}}, "public.tasks"),
        ({"vikunja": {"public.tasks": 0, "public.users": 2}}, "public.tasks"),
    ],
    ids=["missing-database", "missing-table", "emptied-table"],
)
def test_an_incomplete_restore_fails_and_names_what_is_missing(restored: dict, named: str) -> None:
    ok, lines = compare({"vikunja": {"public.tasks": 120, "public.users": 2}}, restored)
    assert not ok
    assert any(named in line and "FAIL" in line for line in lines)


def test_a_table_empty_in_both_is_not_a_failure() -> None:
    ok, _ = compare({"vikunja": {"public.archive": 0}}, {"vikunja": {"public.archive": 0}})
    assert ok


class _Fake:
    """Plays restic, docker and kubectl. Every call is recorded."""

    def __init__(
        self,
        *,
        trailer: bool = True,
        load_rc: int = 0,
        run_rc: int = 0,
        live_tables: bool = True,
        dump_rc: int = 0,
        rm_fails: bool = False,
    ) -> None:
        self.trailer = trailer
        self.load_rc = load_rc
        self.run_rc = run_rc
        self.live_tables = live_tables
        self.dump_rc = dump_rc
        self.rm_fails = rm_fails
        self.exists = False  # the scratch container and its anonymous volume, as docker sees them
        self.calls: list[list[str]] = []
        self.dump_path: Path | None = None

    def __call__(self, argv, *, env=None, stdin=None, stdout_path=None, stderr_to_file=True):
        self.calls.append(argv)
        joined = " ".join(argv)
        if argv[:1] == ["restic"] and "snapshots" in argv:
            return 0, '[{"short_id": "abc12345", "time": "2026-10-01T08:04:00Z"}]', ""
        if argv[:1] == ["restic"] and "dump" in argv:
            if self.dump_rc:
                # A real restic writes its error to stderr; if that went into the
                # dump file, the drill would read an error message as SQL.
                assert stderr_to_file is False
                return self.dump_rc, "", "Fatal: repository is locked"
            body = f"CREATE DATABASE vikunja;\nINSERT '{SECRET}';\n"
            if self.trailer:
                body += f"--\n{TRAILER}\n--\n"
            Path(stdout_path).write_text(body)
            self.dump_path = Path(stdout_path)
            return 0, "", ""
        if "get" in argv and "deploy" in argv:
            return 0, "postgres:16-alpine", ""
        if argv[:3] == ["docker", "container", "inspect"]:
            if not self.exists:
                return 1, "", f"Error: No such container: {argv[-1]}"
            return 0, ("pgvol " if "-f" in argv else "[{}]"), ""
        if argv[:3] == ["docker", "volume", "inspect"]:
            return (0, "[{}]", "") if self.exists else (1, "", f"Error: get {argv[-1]}: no such volume")
        if argv[:2] == ["docker", "rm"]:
            if self.rm_fails:
                return 1, "", "Error response from daemon: removal of container is already in progress"
            self.exists = False
            return 0, argv[-1], ""
        if argv[:2] == ["docker", "run"]:
            self.exists = True  # created even when it then fails to start
            return self.run_rc, "cid", "port is already allocated" if self.run_rc else ""
        if "pg_isready" in joined:
            return 0, "", ""
        if "psql" in joined and stdin is None and stdout_path:
            # A role the image already has is expected and harmless; anything
            # else is a statement that did not load, and its text can carry row data.
            log = 'psql:<stdin>:1: ERROR:  role "postgres" already exists\n'
            if self.load_rc:
                log += f"psql:<stdin>:2: ERROR:  invalid input syntax: {SECRET}\n"
            Path(stdout_path).write_text(log)
            return 0, "", ""
        if "datname" in (stdin or ""):
            return 0, "postgres\nvikunja\n", ""
        if "query_to_xml" in (stdin or ""):
            if not self.live_tables and argv[0] == "kubectl":
                return 0, "", ""
            return 0, "public.tasks|5\npublic.notes|1\n", ""
        return 0, "", ""


@pytest.fixture
def drill(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))
    source = {
        "pvc": {"namespace": "kubelab", "claim": "postgres-data"},
        "pg_dumpall": {"deployment": "postgres", "container": "postgres"},
    }

    def go(fake: _Fake) -> bool:
        return run_drill(
            repo="s3:https://e/b/kubelab-vps",
            restic_env={"RESTIC_PASSWORD": "x"},
            dump_path="/opt/node-backup/staging/postgres/pg_dumpall.sql",
            source=source,
            kubeconfig=tmp_path / "kubeconfig",
            run=fake,
        )

    return go


def test_a_good_dump_passes_names_the_snapshot_and_cleans_up(drill, tmp_path: Path, capsys) -> None:
    fake = _Fake()
    assert drill(fake) is True
    out = capsys.readouterr().out
    assert "abc12345" in out and "trailer" in out
    assert SECRET not in out
    assert not fake.dump_path.parent.exists()


def _removes_container_and_volume(fake: _Fake) -> bool:
    """`-v` is what deletes the restored data: the image keeps it in an anonymous volume."""
    removed = any(c[:2] == ["docker", "rm"] and "-f" in c and "-v" in c for c in fake.calls)
    return removed and not fake.exists


def test_teardown_removes_the_data_volume_with_the_container(drill) -> None:
    fake = _Fake()
    drill(fake)
    assert _removes_container_and_volume(fake)


def test_a_container_that_fails_to_start_is_still_removed_with_its_volume(drill, capsys) -> None:
    """`docker run -d` can create the container and then fail to start it."""
    fake = _Fake(run_rc=125)
    assert drill(fake) is False
    assert "did not start" in capsys.readouterr().out
    assert _removes_container_and_volume(fake)


def test_a_complete_restore_that_leaves_its_data_behind_fails(drill, capsys) -> None:
    """`docker rm` failing must not pass silently: the volume holds the restored dump."""
    fake = _Fake(rm_fails=True)
    assert drill(fake) is False
    out = capsys.readouterr().out
    assert "restores completely" in out  # the restore itself was fine
    assert "still on this machine" in out and "volume pgvol" in out
    assert not fake.dump_path.parent.exists()  # the file goes even when the container does not


def test_live_with_no_tables_is_cannot_check_not_a_pass(drill, capsys) -> None:
    """Every check is per table live has; zero tables would compare nothing and pass (lesson-416)."""
    assert drill(_Fake(live_tables=False)) is False
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_a_restic_failure_is_quoted_and_kept_out_of_the_dump(drill, capsys) -> None:
    fake = _Fake(dump_rc=1)
    assert drill(fake) is False
    assert "repository is locked" in capsys.readouterr().out
    assert not any(c[:2] == ["docker", "run"] for c in fake.calls)


def test_the_restore_uses_the_image_live_runs(drill) -> None:
    fake = _Fake()
    drill(fake)
    run = next(c for c in fake.calls if c[:2] == ["docker", "run"])
    assert run[-1] == "postgres:16-alpine"


def test_a_dump_without_its_trailer_fails_before_any_container_starts(drill, capsys) -> None:
    fake = _Fake(trailer=False)
    assert drill(fake) is False
    assert not any(c[:2] == ["docker", "run"] for c in fake.calls)
    assert "trailer" in capsys.readouterr().out
    assert not fake.dump_path.parent.exists()


def test_a_statement_that_did_not_load_fails_and_is_counted_not_printed(drill, capsys) -> None:
    fake = _Fake(load_rc=1)
    assert drill(fake) is False
    out = capsys.readouterr().out
    assert "1 statement" in out
    assert SECRET not in out
    assert _removes_container_and_volume(fake)
    assert not fake.dump_path.parent.exists()


def test_the_drill_reads_the_path_the_capture_stages() -> None:
    """The snapshot stores absolute paths, so the drill's path must be the capture's."""
    from toolkit.features.postgres_drill import _staging_dir

    repo = Path(__file__).resolve().parents[1]
    template = (repo / "infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2").read_text()
    assert 'mv "$PG_PARTIAL_{{ service }}" "$STAGING/{{ service }}/pg_dumpall.sql"' in template
    assert _staging_dir(repo) == "/opt/node-backup/staging"
