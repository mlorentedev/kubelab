"""`make backup-drill-apps` proves the Authelia and n8n captures in R2 open with the keys in SOPS (BACKUP-068).

"Restores" means: the database is intact, every durable row live had when the
snapshot was taken is in it, and the image live runs opens it with the SOPS key
and no network. Not "equals live": a row created after the snapshot is expected
to be missing.

The restore holds encrypted secrets and the key that opens them, so only table
names, row ids and counts may leave the drill, the key travels only as a `0600`
file, and the container and the directory go on every exit path.
"""

from __future__ import annotations

import json
import shlex
import shutil
import sqlite3
import stat
from pathlib import Path
from typing import Callable, Optional

import pytest

from toolkit.features.app_drill import APPS, compare, parse_rows, rows_sql, run_drill

STAGING = "/opt/node-backup/staging"
IMAGES = {"authelia": "authelia/authelia:4.39.15", "n8n": "n8nio/n8n:2.12.3"}
DATABASES = {"authelia": "db.sqlite3", "n8n": "database.sqlite"}
TAKEN = "2026-10-01T12:04:45.886043275Z"
BEFORE = "2026-09-21 10:00:00.000"  # before the snapshot
AFTER = "2026-10-01 18:00:00.000"  # after it
KEY = "SOPS-KEY-THAT-MUST-NOT-PRINT"
SUB = "4f1c0a2e-opaque-sub-that-must-not-print"


def _authelia_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        create table user_opaque_identifier (id integer primary key autoincrement, service text, sector_id text,
                                             username text, identifier text);
        create table user_preferences (id integer primary key autoincrement, username text, second_factor_method text);
        create table totp_configurations (id integer primary key autoincrement, created_at datetime, username text);
        create table webauthn_credentials (id integer primary key autoincrement, created_at datetime, username text);
        create table migrations (id integer primary key autoincrement, version_after integer);
        insert into migrations (version_after) values (22), (23);
        """
    )
    con.execute(
        "insert into user_opaque_identifier (service, sector_id, username, identifier) values (?, ?, ?, ?)",
        ("openid", "", "manu", SUB),
    )
    con.execute(
        "insert into user_opaque_identifier (service, sector_id, username, identifier) values (?, ?, ?, ?)",
        ("openid", "", "operator", "a-second-sub"),
    )
    con.execute("insert into user_preferences (username, second_factor_method) values ('manu', 'webauthn')")
    con.execute("insert into totp_configurations (created_at, username) values (?, 'manu')", (BEFORE,))
    con.commit()
    con.close()


def _n8n_db(path: Path) -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        create table workflow_entity (id varchar(36) primary key, name text, createdAt datetime);
        create table credentials_entity (id varchar(36) primary key, name text, createdAt datetime);
        """
    )
    for wid in ("d1", "d2", "d3", "d4"):
        con.execute("insert into workflow_entity values (?, ?, ?)", (wid, f"flow {wid}", BEFORE))
    for cid in ("c1", "c2"):
        con.execute("insert into credentials_entity values (?, ?, ?)", (cid, f"cred {cid}", BEFORE))
    con.commit()
    con.close()


BUILD = {"authelia": _authelia_db, "n8n": _n8n_db}


class _Fake:
    """Plays kubectl, ssh (live sqlite3), restic and docker. Every call is recorded.

    Live is a real SQLite file and the ssh answer is the query run against it, so
    the SQL the drill sends is exercised too. The restore starts as a copy of live
    and `mutate` edits it.
    """

    def __init__(
        self,
        tmp: Path,
        service: str,
        *,
        mutate: Optional[Callable[[sqlite3.Connection], None]] = None,
        mutate_live: Optional[Callable[[sqlite3.Connection], None]] = None,
        corrupt: bool = False,
        image_rc: int = 0,
        image_out: Optional[str] = None,
        health_body: Optional[str] = None,
        pv: Optional[str] = None,
        live_rc: int = 0,
        snapshots: str = json.dumps([{"short_id": "a59acffe", "time": TAKEN}]),
        encryption: str = "Storage Encryption Key Validation: SUCCESS",
        healthy: bool = True,
        running: bool = True,
        logs: str = "",
        export_rc: int = 0,
        run_rc: int = 0,
        rm_fails: bool = False,
    ) -> None:
        self.service = service
        self.live = tmp / "live" / DATABASES[service]
        self.live.parent.mkdir()
        BUILD[service](self.live)
        if mutate_live:
            self._edit(self.live, mutate_live)
        self.mutate = mutate
        self.corrupt = corrupt
        self.image_rc = image_rc
        self.image_out = IMAGES[service] if image_out is None else image_out
        self.health_body = health_body
        self.pv = f"{service}-data\t/var/lib/rancher/k3s/storage/pvc-1_kubelab_{service}-data\n" if pv is None else pv
        self.live_rc = live_rc
        self.snapshots = snapshots
        self.encryption = encryption
        self.healthy = healthy
        self.running = running
        self.logs = logs
        self.export_rc = export_rc
        self.run_rc = run_rc
        self.rm_fails = rm_fails
        self.calls: list[list[str]] = []
        self.workdir: Optional[Path] = None
        self.exists = False
        self.key_mode: Optional[int] = None

    @staticmethod
    def _edit(path: Path, change: Callable[[sqlite3.Connection], None]) -> None:
        con = sqlite3.connect(path)
        change(con)
        con.commit()
        con.close()

    def __call__(self, argv: list[str], *, env=None):
        self.calls.append(argv)
        if argv[:1] == ["kubectl"] and "deploy" in argv:
            return (1, "", "forbidden") if self.image_rc else (0, self.image_out, "")
        if argv[:1] == ["kubectl"] and "pv" in argv:
            return 0, self.pv, ""
        if argv[:1] == ["ssh"]:
            if self.live_rc:
                return self.live_rc, "", "sudo: a password is required"
            words = shlex.split(argv[-1])
            assert words[:4] == ["sudo", "-n", "sqlite3", "-readonly"] and words[4] == "-json"
            con = sqlite3.connect(self.live)
            con.row_factory = sqlite3.Row
            rows = [dict(r) for r in con.execute(words[-1])]
            con.close()
            return 0, json.dumps(rows) if rows else "", ""
        if argv[:1] == ["restic"] and "snapshots" in argv:
            return 0, self.snapshots, ""
        if argv[:1] == ["restic"] and "restore" in argv:
            target = Path(argv[argv.index("--target") + 1])
            self.workdir = target
            data = target / STAGING.lstrip("/") / self.service
            data.mkdir(parents=True)
            restored = data / DATABASES[self.service]
            if self.corrupt:
                restored.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4000)
            else:
                shutil.copy(self.live, restored)
                if self.mutate:
                    self._edit(restored, self.mutate)
            return 0, "", ""
        if argv[:3] == ["docker", "container", "inspect"]:
            return (0, "", "") if self.exists else (1, "", f"Error: No such container: {argv[-1]}")
        if argv[:2] == ["docker", "rm"]:
            if self.rm_fails:
                return 1, "", "Error response from daemon: device or resource busy"
            self.exists = False
            return 0, argv[-1], ""
        if argv[:2] == ["docker", "run"]:
            self.exists = True  # created even when it then fails to start
            mount = next(a for a in argv if a.endswith(":/run/drill:ro"))
            self.key_mode = stat.S_IMODE(Path(mount.split(":")[0], "key").stat().st_mode)
            return self.run_rc, "cid", "boom" if self.run_rc else ""
        if argv[:2] == ["docker", "inspect"]:
            return 0, "true\n" if self.running else "false\n", ""
        if argv[:2] == ["docker", "logs"]:
            return 0, "", self.logs
        if argv[:2] == ["docker", "exec"]:
            if "encryption" in argv:
                return 0, self.encryption, ""
            if "wget" in argv:
                if not self.healthy:
                    return 1, "", "wget: can't connect to remote host (127.0.0.1): Connection refused"
                if self.health_body is not None:
                    return 0, self.health_body, ""
                return 0, '{"status":"OK"}' if self.service == "authelia" else '{"status":"ok"}', ""
            if "export:credentials" in argv:
                return self.export_rc, "", ""
            return 0, "", ""
        return 0, "", ""


@pytest.fixture
def drill(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

    def go(fake: _Fake) -> bool:
        ticks = iter(range(0, 100_000, 5))
        return run_drill(
            app=APPS[fake.service],
            database=DATABASES[fake.service],
            repo="s3:https://e/b/kubelab-vps",
            restic_env={"RESTIC_PASSWORD": "x"},
            staging_dir=STAGING,
            key=KEY,
            kubeconfig="/k/kubelab-prod-config",
            namespace="kubelab",
            claim=f"{fake.service}-data",
            ssh_target="deployer@vps",
            run=fake,
            sleep=lambda s: None,
            clock=lambda: float(next(ticks)),
        )

    return go


def _fake(tmp_path: Path, service: str, **kw) -> _Fake:
    root = tmp_path / "fixture"
    root.mkdir(exist_ok=True)
    return _Fake(root, service, **kw)


def _torn_down(fake: _Fake) -> bool:
    removed = any(c[:2] == ["docker", "rm"] and "-f" in c and "-v" in c for c in fake.calls)
    return removed and not fake.exists and (fake.workdir is None or not fake.workdir.exists())


def _started(fake: _Fake) -> bool:
    return any(c[:2] == ["docker", "run"] for c in fake.calls)


def _out(capsys) -> str:
    return " ".join(capsys.readouterr().out.split())


# --- compare ---------------------------------------------------------------

AUTHELIA = APPS["authelia"].tables
SNAP = 1_790_000_000.0


def test_a_complete_restore_passes_and_counts_each_table() -> None:
    rows = {"user_opaque_identifier": {"1": (None, "d1")}, "totp_configurations": {"3": (int(SNAP) - 60, "")}}
    ok, lines = compare(live=rows, restored=rows, tables=AUTHELIA, taken=SNAP)
    assert ok, lines
    assert "user_opaque_identifier: 1 live, 1 restored" in lines


def test_a_row_live_had_at_snapshot_time_must_come_back() -> None:
    live = {"totp_configurations": {"3": (int(SNAP) - 60, "")}}
    ok, lines = compare(live=live, restored={}, tables=AUTHELIA, taken=SNAP)
    assert not ok
    assert any(line.startswith("FAIL totp_configurations row 3") and "missing" in line for line in lines)


def test_a_row_created_after_the_snapshot_is_reported_not_failed() -> None:
    live = {"totp_configurations": {"3": (int(SNAP) + 60, "")}}
    ok, lines = compare(live=live, restored={"totp_configurations": {}}, tables=AUTHELIA, taken=SNAP)
    assert ok
    assert any("row 3: newer than the snapshot" in line for line in lines)


def test_without_a_timestamp_an_id_above_the_restores_highest_is_newer() -> None:
    restored = {"user_preferences": {"1": (None, "")}}
    live = {"user_preferences": {"1": (None, ""), "2": (None, "")}}
    ok, lines = compare(live=live, restored=restored, tables=AUTHELIA, taken=SNAP)
    assert ok
    assert any("user_preferences row 2: newer" in line for line in lines)


def test_without_a_timestamp_a_missing_id_below_the_restores_highest_is_lost() -> None:
    restored = {"user_preferences": {"3": (None, "")}}
    live = {"user_preferences": {"2": (None, ""), "3": (None, "")}}
    ok, lines = compare(live=live, restored=restored, tables=AUTHELIA, taken=SNAP)
    assert not ok
    assert any(line.startswith("FAIL user_preferences row 2") for line in lines)


def test_without_a_timestamp_an_empty_restore_cannot_excuse_a_missing_row() -> None:
    ok, _ = compare(live={"user_preferences": {"1": (None, "")}}, restored={}, tables=AUTHELIA, taken=SNAP)
    assert not ok


def test_an_identity_restored_with_different_contents_fails() -> None:
    live = {"user_opaque_identifier": {"1": (None, "digest-live")}}
    restored = {"user_opaque_identifier": {"1": (None, "digest-other")}}
    ok, lines = compare(live=live, restored=restored, tables=AUTHELIA, taken=SNAP)
    assert not ok
    assert any("row 1: restored with different contents" in line for line in lines)


def test_a_row_deleted_since_the_snapshot_is_reported() -> None:
    ok, lines = compare(
        live={"user_preferences": {}}, restored={"user_preferences": {"1": (None, "")}}, tables=AUTHELIA, taken=SNAP
    )
    assert ok
    assert any("row 1: deleted since the snapshot" in line for line in lines)


def test_identity_values_are_hashed_on_read_and_never_kept() -> None:
    rows, version = parse_rows(
        [
            {"tbl": "user_opaque_identifier", "k": "1", "t": None, "ident": f"'openid','','manu','{SUB}'"},
            {"tbl": "__schema_version__", "k": "23", "t": None, "ident": None},
        ]
    )
    assert version == "23"
    assert SUB not in repr(rows) and len(rows["user_opaque_identifier"]["1"][1]) == 64


def test_the_query_reads_every_declared_table_and_the_schema_version(tmp_path: Path) -> None:
    db = tmp_path / "db.sqlite3"
    _authelia_db(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    rows, version = parse_rows([dict(r) for r in con.execute(rows_sql(APPS["authelia"]))])
    con.close()
    assert version == "23"
    assert set(rows["user_opaque_identifier"]) == {"1", "2"} and set(rows["user_preferences"]) == {"1"}
    assert rows["totp_configurations"]["1"][0] == 1_789_984_800  # 2026-09-21 10:00:00 UTC


# --- the drill, against fakes ------------------------------------------------


@pytest.mark.parametrize("service", ["authelia", "n8n"])
def test_a_good_restore_passes_names_the_snapshot_and_cleans_up(drill, capsys, tmp_path, service) -> None:
    fake = _fake(tmp_path, service)
    assert drill(fake) is True
    out = _out(capsys)
    assert "a59acffe" in out and f"restores {service} completely" in out
    assert KEY not in out and SUB not in out
    assert _torn_down(fake)


@pytest.mark.parametrize("service", ["authelia", "n8n"])
def test_the_key_travels_only_as_a_private_file_into_a_container_with_no_network(drill, tmp_path, service) -> None:
    fake = _fake(tmp_path, service)
    drill(fake)
    start = next(c for c in fake.calls if c[:2] == ["docker", "run"])
    assert start[start.index("--network") + 1] == "none"
    assert "--user" in start
    assert IMAGES[service] in start  # the image the live Deployment runs
    assert f"{APPS[service].key_env}=/run/drill/key" in start
    assert fake.key_mode == 0o600
    assert not any(KEY in arg for call in fake.calls for arg in call)


@pytest.mark.parametrize("service", ["authelia", "n8n"])
def test_live_is_read_from_the_file_never_by_running_the_app_in_its_pod(drill, tmp_path, service) -> None:
    fake = _fake(tmp_path, service)
    drill(fake)
    assert not any(c[:1] == ["kubectl"] and "exec" in c for c in fake.calls)
    live = next(c for c in fake.calls if c[:1] == ["ssh"])
    assert f"/pvc-1_kubelab_{service}-data/{DATABASES[service]}" in live[-1]


def test_a_rotated_opaque_identifier_fails_and_never_starts_a_server(drill, capsys, tmp_path) -> None:
    fake = _fake(
        tmp_path,
        "authelia",
        mutate=lambda con: con.execute("update user_opaque_identifier set identifier = 'other' where id = 1"),
    )
    assert drill(fake) is False
    out = _out(capsys)
    assert "user_opaque_identifier row 1: restored with different contents" in out
    assert SUB not in out and not _started(fake)
    assert _torn_down(fake)


def test_a_workflow_missing_from_the_restore_fails_and_is_named(drill, capsys, tmp_path) -> None:
    fake = _fake(tmp_path, "n8n", mutate=lambda con: con.execute("delete from workflow_entity where id = 'd2'"))
    assert drill(fake) is False
    assert "FAIL workflow_entity row d2: live had it at snapshot time" in _out(capsys)
    assert not _started(fake)


def test_a_workflow_created_after_the_snapshot_does_not_fail(drill, capsys, tmp_path) -> None:
    fake = _fake(
        tmp_path,
        "n8n",
        mutate_live=lambda con: con.execute("insert into workflow_entity values ('d5', 'new', ?)", (AFTER,)),
        mutate=lambda con: con.execute("delete from workflow_entity where id = 'd5'"),
    )
    assert drill(fake) is True
    assert "workflow_entity row d5: newer than the snapshot" in _out(capsys)


def test_a_corrupt_database_fails_and_never_starts_a_server(drill, capsys, tmp_path) -> None:
    fake = _fake(tmp_path, "authelia", corrupt=True)
    assert drill(fake) is False
    assert "integrity_check did not answer ok" in _out(capsys)
    assert not _started(fake) and _torn_down(fake)


def test_authelia_reads_the_encryption_check_text_because_it_exits_0_on_failure(drill, capsys, tmp_path) -> None:
    fake = _fake(tmp_path, "authelia", encryption="Storage Encryption Key Validation: FAILURE")
    assert drill(fake) is False
    assert "the SOPS storage key does not open the restored database" in _out(capsys)
    assert _torn_down(fake)


def test_authelia_checks_the_key_before_starting_the_server(drill, tmp_path) -> None:
    fake = _fake(tmp_path, "authelia")
    drill(fake)
    execs = [c for c in fake.calls if c[:2] == ["docker", "exec"]]
    assert "encryption" in execs[0]
    serve = next(i for i, c in enumerate(execs) if "-d" in c)
    assert serve > 0 and execs[serve][-2:] == ["--config", "/run/drill/config.yml"]


@pytest.mark.parametrize("service", ["authelia", "n8n"])
def test_a_server_that_never_answers_healthy_fails(drill, capsys, tmp_path, service) -> None:
    fake = _fake(tmp_path, service, healthy=False)
    assert drill(fake) is False
    assert "did not answer healthy" in _out(capsys)
    assert _torn_down(fake)


@pytest.mark.parametrize("service", ["authelia", "n8n"])
def test_an_answer_that_is_not_healthy_is_not_a_pass(drill, capsys, tmp_path, service) -> None:
    fake = _fake(tmp_path, service, health_body='{"status":"KO"}')
    assert drill(fake) is False
    assert "did not answer healthy" in _out(capsys)


def test_an_n8n_that_exited_is_not_waited_on(drill, tmp_path) -> None:
    """A container that stopped will never answer; the drill says so at once, not after two minutes."""
    fake = _fake(tmp_path, "n8n", healthy=False, running=False)
    assert drill(fake) is False
    assert sum(1 for c in fake.calls if c[:2] == ["docker", "exec"] and "wget" in c) == 1


def test_n8n_names_a_key_that_is_not_the_datas(drill, capsys, tmp_path) -> None:
    fake = _fake(
        tmp_path,
        "n8n",
        healthy=False,
        running=False,
        logs="Error: Mismatching encryption keys. The encryption key in the settings file does not match",
    )
    assert drill(fake) is False
    out = _out(capsys)
    assert "the SOPS key is not the key this data was encrypted with" in out
    assert "settings file" not in out  # the log line itself is never printed


def test_n8n_fails_when_a_credential_does_not_decrypt(drill, capsys, tmp_path) -> None:
    fake = _fake(tmp_path, "n8n", export_rc=1)
    assert drill(fake) is False
    assert "do not decrypt" in _out(capsys)
    assert _torn_down(fake)


@pytest.mark.parametrize(
    ("kwargs", "named"),
    [
        ({"image_rc": 1}, "image live runs could not be read"),
        ({"image_out": ""}, "image live runs could not be read"),
        ({"pv": ""}, "no local-path volume bound to kubelab/"),
        ({"live_rc": 255}, "live's database could not be read"),
        ({"snapshots": "[]"}, "no snapshot readable"),
    ],
)
def test_live_or_the_repository_that_cannot_be_read_is_cannot_check(drill, capsys, tmp_path, kwargs, named) -> None:
    fake = _fake(tmp_path, "n8n", **kwargs)
    assert drill(fake) is False
    out = _out(capsys)
    assert "CANNOT CHECK" in out and named in out
    assert not _started(fake)


def test_a_live_database_with_no_durable_rows_is_cannot_check(drill, capsys, tmp_path) -> None:
    def empty(con: sqlite3.Connection) -> None:
        con.execute("delete from workflow_entity")
        con.execute("delete from credentials_entity")

    fake = _fake(tmp_path, "n8n", mutate_live=empty)
    assert drill(fake) is False
    assert "CANNOT CHECK — live has no durable rows" in _out(capsys)


def test_a_container_that_fails_to_start_is_still_removed(drill, capsys, tmp_path) -> None:
    fake = _fake(tmp_path, "n8n", run_rc=125)
    assert drill(fake) is False
    assert _torn_down(fake)


def test_a_complete_restore_that_leaves_its_container_behind_fails(drill, capsys, tmp_path) -> None:
    fake = _fake(tmp_path, "authelia", rm_fails=True)
    assert drill(fake) is False


def test_a_complete_restore_that_leaves_the_data_on_disk_fails(drill, capsys, tmp_path, monkeypatch) -> None:
    fake = _fake(tmp_path, "n8n")
    monkeypatch.setattr("toolkit.features.app_drill.shutil.rmtree", lambda *a, **k: None)
    assert drill(fake) is False
    assert "delete it now" in _out(capsys)


def test_the_drill_reads_the_files_keys_and_target_the_ssot_declares(monkeypatch) -> None:
    """The plumbing from `common.yaml` to the drill, which the fakes above cannot see."""
    import yaml

    from toolkit.features import app_drill, backup_destination
    from toolkit.features.configuration import ConfigurationManager

    repo = Path(__file__).resolve().parents[1]
    common = yaml.safe_load((repo / "infra/config/values/common.yaml").read_text())
    seen: list[dict] = []
    asked: list[str] = []
    # Hermetic: no SOPS is decrypted; the key lookup is recorded instead.
    monkeypatch.setattr(ConfigurationManager, "_decrypt_sops", lambda self, path: {})
    monkeypatch.setattr(ConfigurationManager, "get_secret_by_path", lambda self, p: asked.append(p) or "k")
    monkeypatch.setattr(backup_destination, "restic_context", lambda cm: ({}, {}))
    monkeypatch.setattr(backup_destination, "repo_url", lambda dest, name: name)
    monkeypatch.setattr(app_drill, "run_drill", lambda **kw: seen.append(kw) or True)

    assert app_drill.drill_apps(env="prod", project_root=repo)
    sources = common["backup"]["sources"]["vps"]
    assert [kw["app"].service for kw in seen] == ["authelia", "n8n"]
    for kw in seen:
        service = kw["app"].service
        assert kw["database"] == sources[service]["sqlite"]
        assert kw["claim"] == sources[service]["pvc"]["claim"]
        assert (
            kw["ssh_target"]
            == f"{common['networking']['ssh_users']['cloud']}@{common['networking']['vps']['public_ip']}"
        )
    assert asked == [APPS["authelia"].key_path, APPS["n8n"].key_path]
