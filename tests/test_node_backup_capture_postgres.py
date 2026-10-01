"""The capture stages a complete `pg_dumpall`, and refuses anything less (BACKUP-046 AC2).

These run the RENDERED capture script with a fake `kubectl` first on PATH, rather
than reading the template's text: what matters is what the script does when the
exec fails or the dump stops short, and only running it shows that.

A dump is complete when it ends with pg_dumpall's own trailer, `-- PostgreSQL
database cluster dump complete`, measured on prod's 16-alpine on 2026-10-01. A
connection cut mid-stream leaves a file that loads partially and looks like data,
so the trailer is the check, the same role the capture sentinel plays for the
whole run.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

from tests.test_node_backup_role import _render

TRAILER = "-- PostgreSQL database cluster dump complete"
SOURCES = {
    "postgres": {
        "pvc": {"namespace": "kubelab", "claim": "postgres-data"},
        "pg_dumpall": {"deployment": "postgres", "container": "postgres"},
    }
}

FAKE_KUBECTL = """#!/bin/bash
echo "$*" >> "$FAKE_LOG"
case "$FAKE_MODE" in
  ok)        printf -- '--\\n-- PostgreSQL database cluster dump\\n--\\nCREATE DATABASE vikunja;\\n--\\n%s\\n--\\n\\n' "$TRAILER" ;;
  truncated) printf -- '--\\n-- PostgreSQL database cluster dump\\n--\\nCREATE DATABASE vik' ;;
  fail)      echo 'error: unable to upgrade connection: container not found' >&2; exit 1 ;;
esac
"""


@pytest.fixture
def capture(tmp_path: Path):
    staging = tmp_path / "staging"
    sentinel = staging / ".capture-complete"
    script = tmp_path / "capture.sh"
    script.write_text(
        _render(
            "node-backup-capture.sh.j2",
            node_backup_sources=SOURCES,
            inventory_hostname="vps",
            node_backup_location="always-on",
            node_backup_staging_dir=str(staging),
            node_backup_capture_sentinel=str(sentinel),
        )
    )
    bindir = tmp_path / "bin"
    bindir.mkdir()
    kubectl = bindir / "kubectl"
    kubectl.write_text(FAKE_KUBECTL)
    kubectl.chmod(kubectl.stat().st_mode | stat.S_IXUSR)
    log = tmp_path / "kubectl.log"

    def run(mode: str) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "PATH": f"{bindir}:{os.environ['PATH']}",
            "FAKE_MODE": mode,
            "FAKE_LOG": str(log),
            "TRAILER": TRAILER,
        }
        return subprocess.run(["bash", str(script)], capture_output=True, text=True, env=env)

    run.staging = staging  # type: ignore[attr-defined]
    run.sentinel = sentinel  # type: ignore[attr-defined]
    run.log = log  # type: ignore[attr-defined]
    return run


def test_a_complete_dump_is_staged_and_the_capture_completes(capture) -> None:
    proc = capture("ok")
    assert proc.returncode == 0, proc.stderr
    dump = capture.staging / "postgres" / "pg_dumpall.sql"
    assert TRAILER in dump.read_text()
    assert capture.sentinel.exists()
    # Nothing else from the claim: a file copy of a running Postgres is not a backup.
    assert sorted(p.name for p in (capture.staging / "postgres").iterdir()) == ["pg_dumpall.sql"]


def test_the_dump_runs_inside_the_declared_workload_as_its_own_user(capture) -> None:
    capture("ok")
    calls = capture.log.read_text().splitlines()
    assert len(calls) == 1, calls
    call = calls[0]
    assert call.startswith("exec -n kubelab deploy/postgres -c postgres -- ")
    assert 'pg_dumpall -U "$POSTGRES_USER"' in call
    # The data directory is never resolved, so it can never be copied.
    assert "get pv" not in call


def test_a_truncated_dump_fails_the_capture_and_names_the_source(capture) -> None:
    proc = capture("truncated")
    assert proc.returncode != 0
    assert "postgres" in proc.stderr and "complete" in proc.stderr
    assert not capture.sentinel.exists()
    assert not (capture.staging / "postgres" / "pg_dumpall.sql").exists()


def test_a_failed_exec_fails_the_capture_and_names_the_source(capture) -> None:
    proc = capture("fail")
    assert proc.returncode != 0
    assert "node-backup-capture: postgres" in proc.stderr
    assert not capture.sentinel.exists()
