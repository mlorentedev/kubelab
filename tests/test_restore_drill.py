"""The phases the restore drills share (BACKUP-072, #2015).

The four drills each had their own copy of these, and the copies disagreed:
two raised on a snapshot list the other two reported as CANNOT CHECK, and one
took the first snapshot where the others took the last (lesson-505).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolkit.features.restore_drill import latest_snapshot, scratch, wait_until

GOOD = {"short_id": "a59acffe", "time": "2026-10-02T00:01:11Z", "hostname": "kubelab-vps", "paths": ["/staging"]}


def _out(capsys) -> str:
    return " ".join(capsys.readouterr().out.split())


def _restic(rc: int, out: str, calls: list | None = None):
    def run(argv, *, env=None):
        if calls is not None:
            calls.append(argv)
        return rc, out, "Fatal: unable to open repository" if rc else ""

    return run


def test_the_only_snapshot_is_chosen_and_named(capsys) -> None:
    calls: list = []
    snapshot = latest_snapshot(_restic(0, json.dumps([GOOD]), calls), "s3:r", {}, label="drill: n8n")
    assert snapshot == GOOD
    assert calls == [["restic", "-r", "s3:r", "snapshots", "--json", "--latest", "1"]]
    assert "drill: n8n: snapshot a59acffe taken" in _out(capsys)


@pytest.mark.parametrize(
    ("rc", "out", "reason"),
    [
        (1, "", "unable to open repository"),
        (0, "[]", "holds no snapshot"),
        (0, "<html>proxy error</html>", "could not be parsed"),
        (0, '{"error": "x"}', "is not a list"),
        (0, '"x"', "is not a list"),
        (0, json.dumps([{"time": GOOD["time"]}]), "lacks its id or its time"),
        (0, json.dumps([{**GOOD, "time": None}]), "lacks its id or its time"),
        (0, json.dumps(["a59acffe"]), "lacks its id or its time"),
    ],
    ids=["restic-fails", "empty", "malformed", "object", "string", "no-id", "null-time", "not-a-record"],
)
def test_a_snapshot_list_that_cannot_be_used_is_cannot_check_never_a_raise(capsys, rc, out, reason) -> None:
    assert latest_snapshot(_restic(rc, out), "s3:r", {}) is None
    said = _out(capsys)
    assert "CANNOT CHECK — no snapshot readable in s3:r" in said and reason in said


def test_two_capture_groups_are_cannot_check_not_a_choice_by_position(capsys) -> None:
    other = {**GOOD, "short_id": "0badc0de", "paths": ["/elsewhere"]}
    assert latest_snapshot(_restic(0, json.dumps([GOOD, other])), "s3:r", {}) is None
    said = _out(capsys)
    assert "CANNOT CHECK" in said and "2 capture groups" in said and "/elsewhere" in said


class _Docker:
    """Just enough docker for the teardown: a container that is there until `docker rm` succeeds."""

    def __init__(self, *, rm_fails: bool = False) -> None:
        self.rm_fails = rm_fails
        self.exists = True

    def __call__(self, argv, *, env=None):
        if argv[:3] == ["docker", "container", "inspect"]:
            return (0, "", "") if self.exists else (1, "", "Error: No such container")
        if argv[:2] == ["docker", "rm"] and not self.rm_fails:
            self.exists = False
        return 0, "", ""


@pytest.fixture(autouse=True)
def _tmp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))


def test_a_drill_that_ends_clean_says_so() -> None:
    with scratch(_Docker(), "pgdrill", holds="a dump") as box:
        assert box.workdir.is_dir() and box.name.startswith("pgdrill-")
        (box.workdir / "dump.sql").write_text("rows")
    assert box.clean and not box.workdir.exists()


def test_a_drill_that_raises_still_removes_its_container_and_data() -> None:
    docker = _Docker()
    with pytest.raises(RuntimeError), scratch(docker, "hsdrill", holds="keys") as box:
        raise RuntimeError("boom")
    assert not docker.exists and not box.workdir.exists()


def test_a_container_that_survives_its_removal_is_not_clean() -> None:
    with scratch(_Docker(rm_fails=True), "giteadrill", holds="a forge") as box:
        pass
    assert not box.clean and not box.workdir.exists()


def test_data_that_cannot_be_deleted_is_not_clean_and_is_named(capsys) -> None:
    with scratch(_Docker(), "n8ndrill", holds="n8n's data and key", wipe=lambda workdir: False) as box:
        pass
    assert not box.clean
    said = _out(capsys)  # the logger wraps long lines, here inside the path
    assert "could not remove" in said and box.name.split("-")[0] in said
    assert "it holds n8n's data and key, delete it now" in said


def test_the_data_is_deleted_even_when_removing_the_container_raises() -> None:
    def run(argv, *, env=None):
        raise OSError("docker is not installed")

    with pytest.raises(OSError), scratch(run, "pgdrill", holds="a dump") as box:
        pass
    assert not box.workdir.exists() and not box.clean


def test_waiting_stops_when_the_server_answers_and_gives_up_at_the_deadline() -> None:
    now = iter(range(100))
    answers = iter([False, False, True])
    assert wait_until(lambda: next(answers), timeout=50, sleep=lambda s: None, clock=lambda: next(now))
    assert not wait_until(lambda: False, timeout=3, sleep=lambda s: None, clock=lambda: next(now))


def test_a_scratch_without_a_container_never_calls_docker_and_is_clean_once_the_data_is_gone() -> None:
    def no_docker(argv, *, env=None):
        raise AssertionError(f"a directory-only drill ran {argv[0]}")

    with scratch(no_docker, "nodedrill", holds="a node's files", container=False) as box:
        (box.workdir / "webui.db").write_text("rows")
    assert box.clean and not box.workdir.exists()


def test_a_scratch_without_a_container_is_not_clean_when_the_data_stays(capsys) -> None:
    def no_docker(argv, *, env=None):
        raise AssertionError(f"a directory-only drill ran {argv[0]}")

    with scratch(no_docker, "nodedrill", holds="a node's files", wipe=lambda workdir: False, container=False) as box:
        pass
    assert not box.clean
    assert "it holds a node's files, delete it now" in _out(capsys)
