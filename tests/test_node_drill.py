"""`make backup-drill-node` restores a node's file-and-SQLite sources into a scratch directory (BACKUP-076).

The sources are the ones `backup.sources.<node>` declares, so the drill is
generic: ace2 is only the first node it runs on. A restore passes when every
source came back with at least one file, every declared SQLite database is
there and answers `PRAGMA integrity_check` with `ok`, and every declared
`exclude` path stayed out. Nothing but declared names, counts, sizes and
timings leaves the drill, because the restore holds credentials and sessions.

Every failure test asserts the failure's own text: a drill that returned False
for the wrong reason would pass a bare `is False`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Callable, Optional

import pytest
import yaml

from toolkit.features import node_drill
from toolkit.features.node_drill import drill_node, run_drill

REPO = Path(__file__).resolve().parents[1]
STAGING = "/opt/node-backup/staging"
SNAPSHOT = [{"short_id": "46f892f1", "time": "2026-10-07T12:04:45.886043275Z", "hostname": "ace2"}]
CONTENT = "SESSION-TOKEN-THAT-MUST-NOT-PRINT"

SOURCES = {
    "app": {
        "volume": "app-data",
        "sqlite": ["app.db", "nested/state.db"],
        "exclude": {"cache": {"reason": "downloaded again", "tier": 3}},
    },
    "plain": {"path": "/var/lib/plain"},
}


def _db(path: Path, corrupt: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if corrupt:
        path.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4000)
        return
    con = sqlite3.connect(path)
    con.execute("create table t (id integer primary key, secret text)")
    con.execute("insert into t (secret) values (?)", (CONTENT,))
    con.commit()
    con.close()


def _good_app(data: Path) -> None:
    _db(data / "app.db")
    _db(data / "nested/state.db")
    (data / "config.json").write_text(CONTENT)


def _good_plain(data: Path) -> None:
    (data / "notes.txt").write_text(CONTENT)


class _Fake:
    """Plays restic: a snapshot list, and a restore that lays out the staged tree under `--target`."""

    def __init__(
        self,
        *,
        app: Callable[[Path], None] = _good_app,
        plain: Callable[[Path], None] = _good_plain,
        snapshots_rc: int = 0,
        snapshots: Optional[str] = None,
        fail_restore: str = "",
    ) -> None:
        self.builders = {"app": app, "plain": plain}
        self.snapshots_rc = snapshots_rc
        self.snapshots = json.dumps(SNAPSHOT) if snapshots is None else snapshots
        self.fail_restore = fail_restore
        self.calls: list[list[str]] = []
        self.targets: list[Path] = []

    def __call__(self, argv: list[str], *, env=None):
        self.calls.append(argv)
        if argv[:1] != ["restic"]:
            raise AssertionError(f"the drill ran {argv[0]}, which a directory restore does not need")
        if "snapshots" in argv:
            if self.snapshots_rc:
                return self.snapshots_rc, "", "Fatal: unable to open config file: wrong password"
            return 0, self.snapshots, ""
        source = argv[argv.index("--include") + 1].rsplit("/", 1)[1]
        target = Path(argv[argv.index("--target") + 1])
        self.targets.append(target)
        if source == self.fail_restore:
            return 1, "", "Fatal: restore failed"
        data = target / STAGING.lstrip("/") / source
        data.mkdir(parents=True)
        self.builders[source](data)
        return 0, "", ""

    def restores(self) -> list[list[str]]:
        return [c for c in self.calls if "restore" in c]


@pytest.fixture(autouse=True)
def _scratch_in_tmp(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))


def _drill(fake: _Fake, sources: Optional[dict] = None) -> bool:
    ticks = iter(range(0, 100_000, 3))
    return run_drill(
        node="ace2",
        sources=SOURCES if sources is None else sources,
        repo="s3:https://e/kubelab-backup-ace2",
        restic_env={"RESTIC_PASSWORD": "x"},
        staging_dir=STAGING,
        run=fake,
        clock=lambda: float(next(ticks)),
    )


def _said(capsys) -> str:
    return " ".join(capsys.readouterr().out.split())


def test_a_whole_restore_passes_and_says_what_it_checked(capsys) -> None:
    fake = _Fake()
    assert _drill(fake) is True
    said = _said(capsys)
    assert "app: 3 files" in said and "plain: 1 file" in said
    assert "app.db: integrity_check ok" in said and "nested/state.db: integrity_check ok" in said
    assert "cache: absent" in said
    assert "restored in" in said and "checked in" in said
    assert "FAIL" not in said and "CANNOT CHECK" not in said


def test_the_restore_reads_the_staged_source_and_never_a_live_path() -> None:
    fake = _Fake()
    assert _drill(fake)
    includes = sorted(c[c.index("--include") + 1] for c in fake.restores())
    assert includes == [f"{STAGING}/app", f"{STAGING}/plain"]
    # Always into the scratch directory: a restore over a live path would be the incident.
    assert all(t.name.startswith("nodedrill-") for t in fake.targets), fake.targets


def test_no_file_content_reaches_the_output(capsys) -> None:
    assert _drill(_Fake())
    assert CONTENT not in capsys.readouterr().out


def test_a_corrupt_database_fails_by_name(capsys) -> None:
    def corrupt(data: Path) -> None:
        _good_app(data)
        _db(data / "nested/state.db", corrupt=True)

    assert _drill(_Fake(app=corrupt)) is False
    said = _said(capsys)
    assert "FAIL app: nested/state.db: PRAGMA integrity_check did not answer ok" in said
    assert "app.db: integrity_check ok" in said  # the intact one is still reported


def test_a_declared_database_that_did_not_come_back_fails(capsys) -> None:
    def lost(data: Path) -> None:
        _db(data / "app.db")
        (data / "config.json").write_text(CONTENT)

    assert _drill(_Fake(app=lost)) is False
    assert "FAIL app: nested/state.db: declared database is missing from the restore" in _said(capsys)


def test_an_excluded_path_that_came_back_fails(capsys) -> None:
    def leaky(data: Path) -> None:
        _good_app(data)
        (data / "cache").mkdir()
        (data / "cache/model.bin").write_text("x")

    assert _drill(_Fake(app=leaky)) is False
    assert "FAIL app: cache: declared exclude is present in the restore" in _said(capsys)


def test_a_source_that_restored_no_file_fails(capsys) -> None:
    assert _drill(_Fake(plain=lambda data: None)) is False
    assert "FAIL plain: restored no file" in _said(capsys)


def test_a_source_restic_cannot_restore_fails_and_the_others_are_still_checked(capsys) -> None:
    fake = _Fake(fail_restore="app")
    assert _drill(fake) is False
    said = _said(capsys)
    assert "app" in said and "restic could not restore" in said
    assert "plain: 1 file" in said


@pytest.mark.parametrize(
    "fake",
    [
        _Fake(snapshots_rc=1),
        _Fake(snapshots="[]"),
        _Fake(snapshots="not json"),
        _Fake(snapshots=json.dumps([*SNAPSHOT, {**SNAPSHOT[0], "short_id": "0badc0de", "paths": ["/elsewhere"]}])),
    ],
    ids=["unreadable", "empty", "garbled", "two-capture-groups"],
)
def test_a_repository_that_gives_no_snapshot_is_cannot_check_and_restores_nothing(fake, capsys) -> None:
    assert _drill(fake) is False
    assert "CANNOT CHECK" in _said(capsys)
    assert fake.restores() == []


@pytest.mark.parametrize("declared", ["../escape.db", "/etc/passwd"])
def test_a_declared_path_outside_the_source_is_refused_before_anything_is_restored(declared, capsys) -> None:
    fake = _Fake()
    assert _drill(fake, {"app": {"sqlite": declared}}) is False
    said = _said(capsys)
    assert "CANNOT CHECK" in said and f"{declared} is outside its source" in said
    assert fake.restores() == []


def test_a_single_sqlite_string_is_one_database(capsys) -> None:
    assert _drill(_Fake(), {"app": {"sqlite": "app.db"}})
    assert "app.db: integrity_check ok" in _said(capsys)


def test_a_dump_source_is_skipped_by_name_not_checked_as_files(capsys) -> None:
    sources = {**SOURCES, "postgres": {"pg_dumpall": {"deployment": "postgres", "container": "postgres"}}}
    fake = _Fake()
    assert _drill(fake, sources) is True
    assert "postgres: skipped, a logical dump (drill-postgres restores it)" in _said(capsys)
    assert len(fake.restores()) == 2


def test_a_node_with_nothing_to_check_is_cannot_check(capsys) -> None:
    assert _drill(_Fake(), {"postgres": {"pg_dumpall": {}}}) is False
    assert "CANNOT CHECK" in _said(capsys)


def test_the_scratch_directory_is_gone_after_a_pass_and_after_a_failure() -> None:
    passed, failed = _Fake(), _Fake(app=lambda data: None)
    assert _drill(passed) is True and _drill(failed) is False
    assert passed.targets and failed.targets
    assert not any(t.exists() for t in [*passed.targets, *failed.targets])


def test_the_scratch_directory_is_gone_when_a_check_raises(monkeypatch) -> None:
    fake = _Fake()

    def boom(database: Path) -> bool:
        raise RuntimeError("boom")

    monkeypatch.setattr(node_drill, "sqlite_intact", boom)
    with pytest.raises(RuntimeError):
        _drill(fake)
    assert fake.targets and not any(t.exists() for t in fake.targets)


def test_a_restore_that_cannot_be_deleted_is_not_a_pass(monkeypatch, capsys) -> None:
    monkeypatch.setattr("toolkit.features.restore_drill._rmtree", lambda workdir: False)
    assert _drill(_Fake()) is False
    assert "could not remove" in _said(capsys)


# --- The plumbing from common.yaml, which the fakes above cannot see ---------


def _resolve(monkeypatch, node: str) -> dict:
    from toolkit.features import backup_destination
    from toolkit.features.configuration import ConfigurationManager

    seen: dict = {}
    # Hermetic: nothing here is a secret, so nothing is decrypted.
    monkeypatch.setattr(ConfigurationManager, "_decrypt_sops", lambda self, path: {})
    monkeypatch.setattr(backup_destination, "node_restic", lambda cm, n: (f"repo-of-{n}", {"RESTIC_PASSWORD": "x"}))
    monkeypatch.setattr(node_drill, "run_drill", lambda **kw: seen.update(kw) or True)
    seen["result"] = drill_node(node, env="prod", project_root=REPO)
    return seen


def test_ace2_reaches_the_drill_with_the_sources_the_ssot_declares(monkeypatch) -> None:
    common = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
    seen = _resolve(monkeypatch, "ace2")
    assert seen["result"] is True
    assert seen["sources"] == common["backup"]["sources"]["ace2"]
    assert {"open_webui", "hermes"} <= set(seen["sources"])
    assert seen["repo"] == "repo-of-ace2" and seen["node"] == "ace2"
    assert seen["staging_dir"] == STAGING


def test_a_node_that_backs_nothing_up_is_cannot_check(monkeypatch, capsys) -> None:
    seen = _resolve(monkeypatch, "not-a-node")
    assert seen["result"] is False and "sources" not in seen
    assert "CANNOT CHECK" in _said(capsys)


def test_a_destination_that_cannot_be_resolved_is_cannot_check(monkeypatch, capsys) -> None:
    from toolkit.features import backup_destination
    from toolkit.features.configuration import ConfigurationManager

    def refuse(cm, node):
        raise backup_destination.DestinationError("Missing SOPS value at 'backup.nodes.ace2.restic_password'")

    monkeypatch.setattr(ConfigurationManager, "_decrypt_sops", lambda self, path: {})
    monkeypatch.setattr(backup_destination, "node_restic", refuse)
    monkeypatch.setattr(node_drill, "run_drill", lambda **kw: pytest.fail("ran with no credentials"))
    assert drill_node("ace2", env="prod", project_root=REPO) is False
    assert "CANNOT CHECK" in _said(capsys)


# --- The entry points ---------------------------------------------------------


def test_the_make_target_passes_node_and_env_through_and_refuses_an_empty_node() -> None:
    import subprocess

    def dry(*args: str) -> subprocess.CompletedProcess:
        return subprocess.run(["make", "-n", "backup-drill-node", *args], cwd=REPO, capture_output=True, text=True)

    ok = dry("NODE=ace2", "ENV=prod")
    assert ok.returncode == 0, ok.stderr
    assert "backup drill-node --node ace2 --env prod" in ok.stdout
    # A staging typo must not run against the wrong repository silently.
    assert "--env staging" in dry("NODE=ace2", "ENV=staging").stdout
    # Really run, not `-n`: the guard is the recipe's first line and exits before the toolkit starts.
    refused = subprocess.run(["make", "backup-drill-node", "ENV=prod"], cwd=REPO, capture_output=True, text=True)
    assert refused.returncode != 0 and "Usage: make backup-drill-node" in refused.stdout + refused.stderr
    assert "drill-node --node" not in refused.stdout


def test_the_cli_requires_a_node_and_exits_non_zero_when_the_drill_fails(monkeypatch) -> None:
    from typer.testing import CliRunner

    from toolkit.cli.backup import app

    runner = CliRunner()
    assert runner.invoke(app, ["drill-node"]).exit_code != 0
    calls = []
    monkeypatch.setattr(node_drill, "drill_node", lambda node, env, project_root=None: calls.append((node, env)) or False)
    assert runner.invoke(app, ["drill-node", "--node", "ace2", "--env", "prod"]).exit_code == 1
    monkeypatch.setattr(node_drill, "drill_node", lambda node, env, project_root=None: True)
    assert runner.invoke(app, ["drill-node", "--node", "ace2", "--env", "prod"]).exit_code == 0
    assert calls == [("ace2", "prod")]
