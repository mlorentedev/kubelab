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

    def __init__(self, *, trailer: bool = True, load_rc: int = 0) -> None:
        self.trailer = trailer
        self.load_rc = load_rc
        self.calls: list[list[str]] = []
        self.dump_path: Path | None = None

    def __call__(self, argv, *, env=None, stdin=None, stdout_path=None):
        self.calls.append(argv)
        joined = " ".join(argv)
        if argv[:1] == ["restic"] and "snapshots" in argv:
            return 0, '[{"short_id": "abc12345", "time": "2026-10-01T08:04:00Z"}]', ""
        if argv[:1] == ["restic"] and "dump" in argv:
            body = f"CREATE DATABASE vikunja;\nINSERT '{SECRET}';\n"
            if self.trailer:
                body += f"--\n{TRAILER}\n--\n"
            Path(stdout_path).write_text(body)
            self.dump_path = Path(stdout_path)
            return 0, "", ""
        if "get" in argv and "deploy" in argv:
            return 0, "postgres:16-alpine", ""
        if argv[:2] == ["docker", "run"]:
            return 0, "cid", ""
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
            return 0, f"public.tasks|5\npublic.notes|1\n{''}", ""
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
    assert ["docker", "rm", "-f"] == next(c for c in fake.calls if c[:2] == ["docker", "rm"])[:3]
    assert not fake.dump_path.parent.exists()


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
    assert any(c[:2] == ["docker", "rm"] for c in fake.calls)
    assert not fake.dump_path.parent.exists()


def test_the_drill_reads_the_path_the_capture_stages() -> None:
    """The snapshot stores absolute paths, so the drill's path must be the capture's."""
    from toolkit.features.postgres_drill import _staging_dir

    repo = Path(__file__).resolve().parents[1]
    template = (repo / "infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2").read_text()
    assert 'mv "$PG_PARTIAL_{{ service }}" "$STAGING/{{ service }}/pg_dumpall.sql"' in template
    assert _staging_dir(repo) == "/opt/node-backup/staging"
