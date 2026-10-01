"""`make backup-drill-gitea` proves the Beelink capture in R2 brings Gitea back (BACKUP-040).

"Brings back" means: every repository passes `git fsck --full`, the restored
server starts and lists them, and nothing live has is missing or emptied. Not
"equals live": the snapshot can be hours older, so a newer push is expected.
A restored branch head that live does not know is the failure, because that is
history that never existed.

The restore is a full copy of the forge (private repositories, `gitea.db`,
`app.ini`, SSH host keys), so only names and counts may leave the drill, and
the container, its volumes and the directory go on every exit path.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Optional

import pytest

from toolkit.features.gitea_drill import compare, repos_on_disk, run_drill

TOKEN = "SCRATCH-TOKEN-THAT-MUST-NOT-PRINT"
STAGING = "/opt/node-backup/staging"
IMAGE = "gitea/gitea:1.25.5"


def test_repositories_are_read_from_disk_in_lower_case(tmp_path: Path) -> None:
    for repo in ("manu/imagesensortool.git", "teledyne/fae-brain.git", "hefesto/not-a-repo"):
        (tmp_path / "git/repositories" / repo).mkdir(parents=True)
    assert repos_on_disk(tmp_path) == {"manu/imagesensortool", "teledyne/fae-brain"}


def _known(*shas: str):
    return lambda repo, sha: sha in shas


def test_a_complete_restore_passes_even_when_live_has_moved_on() -> None:
    live = {"manu/ImageSensorTool": 3, "personal/resume": 1}
    restored = {"manu/ImageSensorTool": {"main": "a1", "dev": "a2"}, "personal/resume": {"main": "b1"}}
    ok, lines = compare(live, restored, {"manu/imagesensortool", "personal/resume"}, _known("a1", "a2", "b1"))
    assert ok, lines
    assert any("manu/ImageSensorTool" in line and "2 branch" in line and "live 3" in line for line in lines)


@pytest.mark.parametrize(
    ("restored", "on_disk", "named"),
    [
        ({"o/r": {"main": "a1"}}, set(), "missing from the restored repositories"),
        ({}, {"o/r"}, "missing from the restored database"),
        ({"o/r": {}}, {"o/r"}, "restored with no branches"),
        ({"o/r": {"main": "zz"}}, {"o/r"}, "a commit live does not know"),
    ],
    ids=["missing-on-disk", "missing-in-db", "emptied", "unknown-head"],
)
def test_an_incomplete_restore_fails_and_names_the_repository(restored, on_disk, named) -> None:
    ok, lines = compare({"o/r": 1}, restored, on_disk, _known("a1"))
    assert not ok
    assert any(line.startswith("FAIL o/r") and named in line for line in lines), lines


def test_a_repository_empty_in_both_is_not_a_failure() -> None:
    ok, _ = compare({"o/empty": 0}, {"o/empty": {}}, {"o/empty"}, _known())
    assert ok


def test_a_head_live_cannot_answer_for_is_cannot_check_not_a_pass() -> None:
    ok, lines = compare({"o/r": 1}, {"o/r": {"main": "a1"}}, {"o/r"}, lambda repo, sha: None)
    assert not ok
    assert any("CANNOT CHECK" in line for line in lines)


class _Live:
    def __init__(self, repos: Optional[dict] = None, fail: bool = False) -> None:
        self.repos = {"manu/ImageSensorTool": ["a1"], "personal/resume": ["b1"]} if repos is None else repos
        self.fail = fail

    def list_repos(self) -> dict[str, bool]:
        if self.fail:
            raise ConnectionError("git.kubelab.live unreachable")
        return {name: True for name in self.repos}

    def list_branches(self, owner: str, name: str) -> list[dict]:
        return [{"name": f"b{i}"} for i, _ in enumerate(self.repos[f"{owner}/{name}"])]

    def commit_exists(self, owner: str, name: str, sha: str) -> bool:
        return sha in self.repos[f"{owner}/{name}"]


class _Fake:
    """Plays restic, git and docker. Every call is recorded."""

    def __init__(
        self, *, fsck_bad: str = "", run_rc: int = 0, ready: bool = True, heads: Optional[dict] = None
    ) -> None:
        self.fsck_bad = fsck_bad
        self.run_rc = run_rc
        self.ready = ready
        self.heads = heads or {"manu/ImageSensorTool": {"main": "a1"}, "personal/resume": {"main": "b1"}}
        self.calls: list[list[str]] = []
        self.workdir: Optional[Path] = None
        self.exists = False  # the scratch container, as docker sees it

    def __call__(self, argv: list[str], *, env=None):
        self.calls.append(argv)
        if argv[:1] == ["restic"] and "snapshots" in argv:
            return 0, '[{"short_id": "beaa6d4b", "time": "2026-10-01T08:49:35Z"}]', ""
        if argv[:1] == ["restic"] and "restore" in argv:
            target = Path(argv[argv.index("--target") + 1])
            self.workdir = target
            data = target / STAGING.lstrip("/") / "gitea"
            for repo in self.heads:  # Gitea stores owner and name in lower case on disk
                (data / "git/repositories" / f"{repo.lower()}.git").mkdir(parents=True)
            (data / "gitea/conf").mkdir(parents=True)
            (data / "gitea/conf/app.ini").write_text("SECRET_KEY = do-not-print\n")
            return 0, "", ""
        if argv[:1] == ["git"]:
            return (1 if self.fsck_bad and self.fsck_bad in argv[2] else 0), "", ""
        if argv[:3] == ["docker", "container", "inspect"]:
            # A bind mount, not a volume: `-f` lists no volume names.
            return (0, "", "") if self.exists else (1, "", f"Error: No such container: {argv[-1]}")
        if argv[:2] == ["docker", "rm"]:
            self.exists = False
            return 0, argv[-1], ""
        if argv[:2] == ["docker", "run"] and "-d" in argv:
            self.exists = True  # created even when it then fails to start
            return self.run_rc, "cid", "Conflict. The container name is already in use" if self.run_rc else ""
        if "healthz" in " ".join(argv):
            return (0 if self.ready else 1), "", ""
        if "generate-access-token" in argv:
            return 0, TOKEN + "\n", ""
        if argv[:2] == ["docker", "exec"] and "wget" in argv:
            url = argv[-1]
            if "/repos/search" in url:
                owners = [{"owner": {"username": f.split("/")[0]}, "name": f.split("/")[1]} for f in self.heads]
                return 0, json.dumps({"data": owners}), ""
            full = url.split("/repos/")[1].split("/branches")[0]
            if not self.heads[full]:
                return 0, "null", ""  # what Gitea answers for a repository with no commits
            return 0, json.dumps([{"name": b, "commit": {"id": s}} for b, s in self.heads[full].items()]), ""
        if argv[:3] == ["docker", "run", "--rm"]:
            # The root-run wipe: the real one empties the bind-mounted directory.
            for child in Path(argv[argv.index("-v") + 1].split(":")[0]).iterdir():
                subprocess.run(["rm", "-rf", str(child)], check=True)
            return 0, "", ""
        return 0, "", ""


@pytest.fixture
def drill(tmp_path: Path, monkeypatch):
    monkeypatch.setattr("tempfile.tempdir", str(tmp_path))

    def go(fake: _Fake, live: Optional[_Live] = None) -> bool:
        ticks = iter(range(0, 100_000, 5))  # each read of the clock advances 5s
        return run_drill(
            repo="s3:https://e/b/kubelab-beelink",
            restic_env={"RESTIC_PASSWORD": "x"},
            staging_dir=STAGING,
            image=IMAGE,
            admin_user="manu",
            live=live or _Live(),
            run=fake,
            sleep=lambda s: None,
            clock=lambda: float(next(ticks)),
        )

    return go


def _torn_down(fake: _Fake) -> bool:
    removed = any(c[:2] == ["docker", "rm"] and "-f" in c and "-v" in c for c in fake.calls)
    return removed and not fake.exists and (fake.workdir is None or not fake.workdir.exists())


def test_a_good_restore_passes_names_the_snapshot_and_cleans_up(drill, capsys) -> None:
    fake = _Fake()
    assert drill(fake) is True
    out = capsys.readouterr().out
    assert "beaa6d4b" in out and "restores Gitea completely" in out
    assert TOKEN not in out and "do-not-print" not in out
    assert _torn_down(fake)


def test_the_restored_server_has_no_network_and_runs_the_pinned_image(drill) -> None:
    fake = _Fake()
    drill(fake)
    start = next(c for c in fake.calls if c[:2] == ["docker", "run"] and "-d" in c)
    assert start[start.index("--network") + 1] == "none"
    assert start[-1] == IMAGE


def test_a_corrupt_repository_fails_names_it_and_never_starts_a_server(drill, capsys) -> None:
    fake = _Fake(fsck_bad="resume.git")
    assert drill(fake) is False
    assert "personal/resume: git fsck --full failed" in capsys.readouterr().out
    assert not any(c[:2] == ["docker", "run"] and "-d" in c for c in fake.calls)
    assert _torn_down(fake)


def test_a_server_that_fails_to_start_is_still_removed_with_its_volumes(drill, capsys) -> None:
    fake = _Fake(run_rc=125)
    assert drill(fake) is False
    assert "did not start" in capsys.readouterr().out
    assert _torn_down(fake)


def test_a_server_that_never_answers_fails(drill, capsys) -> None:
    fake = _Fake(ready=False)
    assert drill(fake) is False
    assert "did not answer" in capsys.readouterr().out
    assert _torn_down(fake)


def test_a_restored_head_live_does_not_know_fails(drill, capsys) -> None:
    fake = _Fake(heads={"manu/ImageSensorTool": {"main": "a1"}, "personal/resume": {"main": "forged"}})
    assert drill(fake) is False
    assert "personal/resume" in capsys.readouterr().out
    assert _torn_down(fake)


@pytest.mark.parametrize("live", [_Live(fail=True), _Live(repos={})], ids=["unreachable", "empty"])
def test_live_that_cannot_be_read_or_lists_nothing_is_cannot_check(drill, capsys, live) -> None:
    fake = _Fake()
    assert drill(fake, live) is False
    assert "CANNOT CHECK" in capsys.readouterr().out
    assert not any(c[:2] == ["restic"] and "restore" in c for c in fake.calls)


def test_the_drill_restores_the_path_the_capture_stages() -> None:
    """The snapshot stores absolute paths, so the drill's must be the capture's."""
    from toolkit.features.postgres_drill import staging_dir

    repo = Path(__file__).resolve().parents[1]
    assert staging_dir(repo) == STAGING


def test_a_repository_empty_live_and_restored_passes(drill) -> None:
    """Gitea answers `/branches` of an empty repository with `null`, on both sides."""
    live = _Live(repos={"manu/ImageSensorTool": ["a1"], "personal/resume": ["b1"], "teledyne/openkm-brain": []})
    fake = _Fake(
        heads={"manu/ImageSensorTool": {"main": "a1"}, "personal/resume": {"main": "b1"}, "teledyne/openkm-brain": {}}
    )
    assert drill(fake, live) is True


def test_a_scratch_read_that_fails_is_cannot_check(drill, capsys) -> None:
    fake = _Fake()
    original = fake.__call__

    def failing(argv, *, env=None):
        if argv[:2] == ["docker", "exec"] and "wget" in argv and "/branches" in argv[-1]:
            return 1, "", "connection refused"
        return original(argv, env=env)

    assert drill(failing) is False
    assert "CANNOT CHECK" in capsys.readouterr().out
