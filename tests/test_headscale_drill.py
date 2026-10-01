"""`make backup-drill-headscale` proves the VPS capture in R2 brings the mesh's control plane back (BACKUP-067).

"Brings back" means: the database is intact, the server keys are live's (so a
node reconnects without re-registering), the restored server starts, and every
node and user live had when the snapshot was taken is in it. Not "equals live":
a node registered after the snapshot is expected to be missing.

The restore holds both private keys, so only names, ids and counts may leave the
drill, and the container and the directory go on every exit path.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Optional

import pytest

from toolkit.features.headscale_drill import compare, parse_entries, run_drill

STAGING = "/opt/node-backup/staging"
IMAGE = "headscale/headscale:v0.28.0"
TAKEN = "2026-10-01T12:04:45.886043275Z"
BEFORE = 1_790_000_000  # 2026-09-21, before the snapshot
AFTER = 1_790_000_000 + 30 * 86400  # after it

NOISE = "privkey:NOISE-KEY-THAT-MUST-NOT-PRINT"
DERP = "privkey:DERP-KEY-THAT-MUST-NOT-PRINT"


def _node(node_id: int, name: str, machine_key: str, created: int = BEFORE, user: str = "kubelab") -> dict:
    return {
        "id": str(node_id),
        "given_name": name,
        "machine_key": machine_key,
        "created_at": {"seconds": str(created), "nanos": 1},
        "user": {"name": user},
    }


def _user(user_id: int, name: str, created: int = BEFORE) -> dict:
    return {"id": str(user_id), "name": name, "created_at": {"seconds": str(created)}}


def test_entries_are_keyed_by_id_and_carry_creation_time() -> None:
    entries = parse_entries(json.dumps([_node(64, "gcp1", "mkey:a")]), key="machine_key")
    assert entries == {64: ("gcp1", "mkey:a", float(BEFORE))}


def test_proto_json_without_created_at_is_treated_as_old() -> None:
    """A missing timestamp must not exempt an entry from the check."""
    entry = {"id": "1", "name": "manu"}
    assert parse_entries(json.dumps([entry]), key=None) == {1: ("manu", "", 0.0)}


def _compare(live_nodes, restored_nodes, live_users=None, restored_users=None):
    users = {1: ("kubelab", "", float(BEFORE))}
    return compare(
        live_nodes=live_nodes,
        restored_nodes=restored_nodes,
        live_users=users if live_users is None else live_users,
        restored_users=users if restored_users is None else restored_users,
        taken=float(BEFORE + 86400),
    )


def test_a_complete_restore_passes() -> None:
    nodes = {2: ("kubelab-vps", "mkey:v", float(BEFORE)), 64: ("gcp1", "mkey:g", float(BEFORE))}
    ok, lines = _compare(nodes, dict(nodes))
    assert ok, lines
    assert any("2 node" in line and "1 user" in line for line in lines), lines


@pytest.mark.parametrize(
    ("restored", "named"),
    [
        ({}, "missing from the restore"),
        ({64: ("gcp1", "mkey:OTHER", float(BEFORE))}, "different machine key"),
    ],
    ids=["missing", "machine-key"],
)
def test_a_node_live_had_at_snapshot_time_must_come_back_unchanged(restored, named) -> None:
    ok, lines = _compare({64: ("gcp1", "mkey:g", float(BEFORE))}, restored)
    assert not ok
    assert any(line.startswith("FAIL gcp1 (id 64)") and named in line for line in lines), lines
    assert not any("mkey:" in line for line in lines), "a machine key is never printed"


def test_a_node_reregistered_under_the_same_name_is_matched_by_id_not_name() -> None:
    """gcp1 re-registers after a preemption: same name, new id. The old id is gone live."""
    live = {65: ("gcp1", "mkey:new", float(AFTER))}
    restored = {64: ("gcp1", "mkey:old", float(BEFORE))}
    ok, lines = _compare(live, restored)
    assert ok, lines
    assert any("gcp1 (id 65)" in line and "newer than the snapshot" in line for line in lines)
    assert any("gcp1 (id 64)" in line and "deleted since the snapshot" in line for line in lines)


def test_a_missing_user_fails_and_a_newer_one_is_reported() -> None:
    live_users = {1: ("kubelab", "", float(BEFORE)), 4: ("agents", "", float(AFTER)), 3: ("work", "", float(BEFORE))}
    restored_users = {1: ("kubelab", "", float(BEFORE))}
    ok, lines = _compare({}, {}, live_users, restored_users)
    assert not ok
    assert any(line.startswith("FAIL user work") for line in lines), lines
    assert any("user agents" in line and "newer than the snapshot" in line for line in lines), lines


def _db(path: Path, corrupt: bool = False) -> None:
    if corrupt:
        path.write_bytes(b"SQLite format 3\x00" + b"\xff" * 4000)
        return
    con = sqlite3.connect(path)
    con.execute("create table nodes (id integer primary key)")
    con.commit()
    con.close()


class _Fake:
    """Plays ssh (live), restic and docker. Every call is recorded."""

    def __init__(
        self,
        *,
        restored_noise: str = NOISE,
        restored_derp: str = DERP,
        missing: str = "",
        corrupt_db: bool = False,
        run_rc: int = 0,
        ready: bool = True,
        exec_out: Optional[str] = None,
        live_nodes: Optional[list] = None,
        restored_nodes: Optional[list] = None,
        live_rc: int = 0,
        hashes_rc: int = 0,
        snapshots: str = json.dumps([{"short_id": "46f892f1", "time": TAKEN}]),
        rm_fails: bool = False,
    ) -> None:
        self.rm_fails = rm_fails
        self.restored = {"noise_private.key": restored_noise, "derp_server_private.key": restored_derp}
        self.missing = missing
        self.corrupt_db = corrupt_db
        self.run_rc = run_rc
        self.ready = ready
        self.exec_out = exec_out
        default = [_node(2, "kubelab-vps", "mkey:v"), _node(64, "gcp1", "mkey:g")]
        self.live_nodes = default if live_nodes is None else live_nodes
        self.restored_nodes = default if restored_nodes is None else restored_nodes
        self.users = [_user(1, "manu"), _user(2, "kubelab")]
        self.live_rc = live_rc
        self.hashes_rc = hashes_rc
        self.snapshots = snapshots
        self.calls: list[list[str]] = []
        self.workdir: Optional[Path] = None
        self.exists = False

    def __call__(self, argv: list[str], *, env=None):
        self.calls.append(argv)
        joined = " ".join(argv)
        if argv[:1] == ["ssh"]:
            if "sha256sum" in joined:
                if self.hashes_rc:
                    return self.hashes_rc, "", "sudo: a password is required"
                lines = [
                    f"{hashlib.sha256(v.encode()).hexdigest()}  /var/lib/docker/volumes/x/_data/{k}"
                    for k, v in (("noise_private.key", NOISE), ("derp_server_private.key", DERP))
                ]
                return 0, "\n".join(lines) + "\n", ""
            if self.live_rc:
                return self.live_rc, "", "ssh: connect to host timed out"
            payload = self.live_nodes if "nodes list" in joined else self.users
            return 0, json.dumps(payload), ""
        if argv[:1] == ["restic"] and "snapshots" in argv:
            return 0, self.snapshots, ""
        if argv[:1] == ["restic"] and "restore" in argv:
            target = Path(argv[argv.index("--target") + 1])
            self.workdir = target
            data = target / STAGING.lstrip("/") / "headscale"
            data.mkdir(parents=True)
            for name, value in self.restored.items():
                if name != self.missing:
                    (data / name).write_text(value)
            if self.missing != "db.sqlite":
                _db(data / "db.sqlite", corrupt=self.corrupt_db)
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
            return self.run_rc, "cid", "boom" if self.run_rc else ""
        if argv[:2] == ["docker", "exec"]:
            if not self.ready:
                return 1, "", "dial unix headscale.sock: connect: no such file or directory"
            if self.exec_out is not None:
                return 0, self.exec_out, ""
            payload = self.restored_nodes if "nodes" in argv else self.users
            return 0, json.dumps(payload), ""
        return 0, "", ""


@pytest.fixture
def drill(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

    def go(fake) -> bool:
        ticks = iter(range(0, 100_000, 5))
        return run_drill(
            repo="s3:https://e/b/kubelab-vps",
            restic_env={"RESTIC_PASSWORD": "x"},
            staging_dir=STAGING,
            image=IMAGE,
            volume="headscale_headscale_data",
            ssh_target="manu@vps",
            cidr="100.64.0.0/10",
            run=fake,
            sleep=lambda s: None,
            clock=lambda: float(next(ticks)),
        )

    return go


def _torn_down(fake: _Fake) -> bool:
    removed = any(c[:2] == ["docker", "rm"] and "-f" in c and "-v" in c for c in fake.calls)
    return removed and not fake.exists and (fake.workdir is None or not fake.workdir.exists())


def _started(fake: _Fake) -> bool:
    return any(c[:2] == ["docker", "run"] for c in fake.calls)


def test_a_good_restore_passes_names_the_snapshot_and_cleans_up(drill, capsys) -> None:
    fake = _Fake()
    assert drill(fake) is True
    out = " ".join(capsys.readouterr().out.split())
    assert "46f892f1" in out and "restores Headscale completely" in out
    assert "noise key: match" in out and "DERP key: match" in out
    assert "NOISE-KEY" not in out and "DERP-KEY" not in out and "mkey:" not in out
    assert _torn_down(fake)


def test_the_restored_server_has_no_network_runs_as_the_caller_and_the_image_it_is_given(drill) -> None:
    fake = _Fake()
    drill(fake)
    start = next(c for c in fake.calls if c[:2] == ["docker", "run"])
    assert start[start.index("--network") + 1] == "none"
    assert "--user" in start
    assert IMAGE in start and start[-1] == "serve"


@pytest.mark.parametrize("missing", ["db.sqlite", "noise_private.key", "derp_server_private.key"])
def test_a_capture_missing_a_file_fails_names_it_and_never_starts_a_server(drill, capsys, missing) -> None:
    fake = _Fake(missing=missing)
    assert drill(fake) is False
    assert missing in capsys.readouterr().out
    assert not _started(fake)
    assert _torn_down(fake)


def test_a_corrupt_database_fails_and_never_starts_a_server(drill, capsys) -> None:
    fake = _Fake(corrupt_db=True)
    assert drill(fake) is False
    assert "db.sqlite" in capsys.readouterr().out
    assert not _started(fake)
    assert _torn_down(fake)


@pytest.mark.parametrize(("kwarg", "label"), [("restored_noise", "noise key"), ("restored_derp", "DERP key")])
def test_a_key_that_differs_from_live_fails(drill, capsys, kwarg, label) -> None:
    fake = _Fake(**{kwarg: "privkey:SOMETHING-ELSE"})
    assert drill(fake) is False
    out = " ".join(capsys.readouterr().out.split())
    assert f"{label}: mismatch" in out
    assert "SOMETHING-ELSE" not in out
    assert _torn_down(fake)


def test_a_server_that_fails_to_start_is_still_removed(drill, capsys) -> None:
    fake = _Fake(run_rc=125)
    assert drill(fake) is False
    assert "did not start" in capsys.readouterr().out
    assert _torn_down(fake)


def test_a_server_that_never_answers_fails(drill, capsys) -> None:
    fake = _Fake(ready=False)
    assert drill(fake) is False
    assert "did not answer" in capsys.readouterr().out
    assert _torn_down(fake)


def test_a_node_missing_from_the_restore_fails_and_is_named(drill, capsys) -> None:
    fake = _Fake(restored_nodes=[_node(2, "kubelab-vps", "mkey:v")])
    assert drill(fake) is False
    assert "gcp1 (id 64)" in capsys.readouterr().out
    assert _torn_down(fake)


@pytest.mark.parametrize(
    "fake",
    [
        _Fake(live_rc=255),
        _Fake(live_nodes=[]),
        _Fake(hashes_rc=1),
    ],
    ids=["live-unreachable", "live-empty", "hashes-unreadable"],
)
def test_live_that_cannot_be_read_is_cannot_check(drill, capsys, fake) -> None:
    assert drill(fake) is False
    assert "CANNOT CHECK" in capsys.readouterr().out
    assert not any(c[:1] == ["restic"] and "restore" in c for c in fake.calls)


def test_no_readable_snapshot_is_cannot_check(drill, capsys) -> None:
    fake = _Fake(snapshots="[]")
    assert drill(fake) is False
    assert "CANNOT CHECK" in capsys.readouterr().out


def test_the_drill_restores_the_path_the_capture_stages() -> None:
    from toolkit.features.postgres_drill import staging_dir

    repo = Path(__file__).resolve().parents[1]
    assert staging_dir(repo) == STAGING


def test_a_complete_restore_that_leaves_its_container_behind_fails(drill, capsys) -> None:
    fake = _Fake(rm_fails=True)
    assert drill(fake) is False
    assert "still on this machine" in capsys.readouterr().out


def test_a_complete_restore_that_leaves_the_keys_on_disk_fails(drill, capsys, monkeypatch) -> None:
    monkeypatch.setattr("toolkit.features.headscale_drill.shutil.rmtree", lambda *a, **k: None)
    fake = _Fake()
    assert drill(fake) is False
    assert "private keys, delete it now" in " ".join(capsys.readouterr().out.split())


@pytest.mark.parametrize("exec_out", ["", "WRN something\n[]", json.dumps([{"given_name": "no-id"}])])
def test_a_restored_list_that_cannot_be_read_is_cannot_check(drill, capsys, exec_out) -> None:
    fake = _Fake(exec_out=exec_out)
    assert drill(fake) is False
    assert "CANNOT CHECK" in capsys.readouterr().out
    assert _torn_down(fake)


def test_the_drill_runs_the_image_volume_and_pool_the_ssot_declares(monkeypatch) -> None:
    """The plumbing from `common.yaml` to the drill, which the fakes above cannot see."""
    import yaml

    from toolkit.features import backup_destination, headscale_drill

    repo = Path(__file__).resolve().parents[1]
    common = yaml.safe_load((repo / "infra/config/values/common.yaml").read_text())
    seen: dict = {}
    from toolkit.features.configuration import ConfigurationManager

    # Hermetic: no value here is a secret, so nothing is decrypted.
    monkeypatch.setattr(ConfigurationManager, "_decrypt_sops", lambda self, path: {})
    monkeypatch.setattr(backup_destination, "restic_context", lambda cm: ({}, {}))
    monkeypatch.setattr(backup_destination, "repo_url", lambda dest, name: name)
    monkeypatch.setattr(headscale_drill, "run_drill", lambda **kw: seen.update(kw) or True)

    assert headscale_drill.drill_headscale(env="prod", project_root=repo)
    assert seen["image"] == common["apps"]["services"]["core"]["headscale"]["image"]
    assert seen["volume"] == common["backup"]["sources"]["vps"]["headscale"]["volume"]
    assert seen["cidr"] == common["networking"]["tailscale_cidr"]
    assert seen["ssh_target"].endswith("@" + common["networking"]["vps"]["public_ip"])
