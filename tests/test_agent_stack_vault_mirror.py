"""The read-only vault the MCP bridge serves Open WebUI (ADR-068 D5 and D6,
spec AI-009 AC9).

The bridge reads a checkout that root owns and a unit refreshes from the vault's
remote, never the agent's clone: the agent writes its clone's zone, so a tool
reading that clone would serve the agent's unpushed words as the vault. The
script runs here against a real bare repository standing in for the remote.
"""

from __future__ import annotations

import configparser
import subprocess
from pathlib import Path

import pytest

from tests.test_agent_stack_role import _environment, _resolved, _tasks
from tests.test_hermes_vault_sync import BRANCH, HERMES, SYNC, _git, _git_env, _write

MIRROR_UNIT = "agent-stack-vault-mirror"


def _render(name: str, **overrides: object) -> str:
    env = _environment()
    return env.get_template(name).render(**{**_resolved(env), **overrides})


def _defaults() -> dict:
    return _resolved(_environment())


class Remote:
    """The vault's remote, written to by another clone."""

    def __init__(self, tmp: Path) -> None:
        self.bare = tmp / "origin.git"
        self.work = tmp / "writer"
        subprocess.run(["git", "init", "-q", "--bare", "-b", BRANCH, str(self.bare)], check=True)
        subprocess.run(["git", "clone", "-q", str(self.bare), str(self.work)], check=True, env=_git_env())
        for key, value in (("user.name", "operator"), ("user.email", "op@example.test"), ("commit.gpgsign", "false")):
            _git(self.work, "config", key, value)

    def commit(self, path: str, text: str) -> str:
        _write(self.work, path, text)
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "-q", "-m", f"write {path}")
        assert _git(self.work, "push", "-q", "origin", f"HEAD:{BRANCH}").returncode == 0
        return _git(self.work, "rev-parse", "HEAD").stdout.strip()


@pytest.fixture
def mirror(tmp_path: Path) -> tuple[Remote, Path, Path]:
    remote = Remote(tmp_path)
    remote.commit("10_projects/kubelab/roadmap.md", "seed\n")
    root = tmp_path / "mirror"
    script = tmp_path / "vault-mirror"
    script.write_text(
        _render(
            "vault-mirror.sh.j2",
            agent_stack_vault_mirror=str(root),
            agent_stack_hermes={**HERMES, "vault_sync": {**SYNC, "remote": remote.bare.as_uri()}},
        )
    )
    script.chmod(0o755)
    return remote, root, script


def _run(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(script)], capture_output=True, text=True, check=False, env=_git_env())


# --------------------------------------------------------------------------- the script


def test_the_first_run_checks_out_the_tip_with_no_git_directory_in_the_tree(mirror) -> None:
    _, root, script = mirror
    assert _run(script).returncode == 0
    tree = root / "tree"
    assert (tree / "10_projects/kubelab/roadmap.md").read_text() == "seed\n"
    # The bridge mounts the tree alone: no history, no remote, no config.
    assert not (tree / ".git").exists()


def test_a_run_follows_the_remote_and_keeps_one_commit(mirror) -> None:
    remote, root, script = mirror
    _run(script)
    tip = remote.commit("10_projects/kubelab/roadmap.md", "moved on\n")
    assert _run(script).returncode == 0
    assert (root / "tree/10_projects/kubelab/roadmap.md").read_text() == "moved on\n"
    gitdir = root / "git"
    assert _git(gitdir, "rev-parse", "HEAD").stdout.strip() == tip
    assert _git(gitdir, "rev-list", "--count", "HEAD").stdout.strip() == "1"


def test_anything_written_into_the_tree_is_discarded(mirror) -> None:
    _, root, script = mirror
    _run(script)
    tree = root / "tree"
    (tree / "10_projects/kubelab/roadmap.md").write_text("tampered\n")
    (tree / "planted.md").write_text("not the vault\n")
    assert _run(script).returncode == 0
    assert (tree / "10_projects/kubelab/roadmap.md").read_text() == "seed\n"
    assert not (tree / "planted.md").exists()


def test_a_file_deleted_upstream_leaves_the_tree(mirror) -> None:
    remote, root, script = mirror
    remote.commit("gone.md", "x\n")
    _run(script)
    assert (root / "tree/gone.md").exists()
    (remote.work / "gone.md").unlink()
    _git(remote.work, "commit", "-q", "-am", "drop")
    _git(remote.work, "push", "-q", "origin", f"HEAD:{BRANCH}")
    _run(script)
    assert not (root / "tree/gone.md").exists()


def test_an_unreachable_remote_fails_and_keeps_the_last_tree(mirror, tmp_path: Path) -> None:
    _, root, script = mirror
    _run(script)
    (tmp_path / "origin.git").rename(tmp_path / "moved.git")
    result = _run(script)
    assert result.returncode != 0
    assert (root / "tree/10_projects/kubelab/roadmap.md").read_text() == "seed\n"


# --------------------------------------------------------------------------- the unit


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(_render(name))
    return parser


def test_the_mirror_is_root_s_and_outside_the_agent_s_reach() -> None:
    d = _defaults()
    mirror = d["agent_stack_vault_mirror"]
    assert not mirror.startswith(d["agent_stack_agent_home"].rstrip("/") + "/")
    assert mirror != d["agent_stack_vault_clone"]
    assert mirror.startswith(d["agent_stack_dir"].rstrip("/") + "/"), "inside the root-only stack directory"


def test_the_unit_runs_as_root_and_cannot_see_the_agent_s_clone() -> None:
    d = _defaults()
    service = _unit("vault-mirror.service.j2")["Service"]
    assert "User" not in service
    assert service["ReadWritePaths"] == d["agent_stack_vault_mirror"]
    assert d["agent_stack_agent_home"] in service["InaccessiblePaths"].split()
    assert service["ProtectSystem"] == "strict"
    assert service["LoadCredential"] == f"vault-token:{d['agent_stack_vault_token_file']}"
    assert service["UMask"] == "0022", "the bridge's non-root user reads the tree"
    assert service["ExecStart"] == f"{d['agent_stack_vault_libexec']}/vault-mirror"


def test_the_unit_pages_on_failure_and_the_timer_follows_the_sync_interval() -> None:
    assert _unit("vault-mirror.service.j2")["Unit"]["OnFailure"] == "kubelab-notify@%n.service"
    timer = _unit("vault-mirror.timer.j2")["Timer"]
    assert timer["OnUnitActiveSec"] == SYNC["interval"]


def test_the_script_uses_the_token_by_credential_helper_only() -> None:
    script = _render("vault-mirror.sh.j2")
    d = _defaults()
    assert f"credential.helper={d['agent_stack_vault_libexec']}/vault-credential" in script
    assert "x-access-token" not in script
    assert "core.hooksPath=/dev/null" in script


# --------------------------------------------------------------------------- the tasks


def _mirror_tasks() -> list[dict]:
    return [t for t in _tasks() if "mirror" in t.get("name", "").lower()]


def test_the_role_installs_runs_and_enables_the_mirror() -> None:
    names = " | ".join(t["name"] for t in _mirror_tasks())
    for step in ("Install the vault mirror", "Run the vault mirror once", "Enable the vault mirror timer"):
        assert step in names, names
    owned = [t for t in _tasks() if (t.get("ansible.builtin.file") or {}).get("path") == "{{ agent_stack_vault_mirror }}"]
    assert owned and owned[0]["ansible.builtin.file"]["owner"] == "root"


def test_the_run_is_proved_by_the_commit_it_checked_out() -> None:
    [proof] = [t for t in _mirror_tasks() if t["name"].startswith("Verify the vault mirror")]
    argv = proof["ansible.builtin.command"]["argv"]
    assert argv[:3] == ["git", "--git-dir", "{{ agent_stack_vault_mirror }}/git"] and "HEAD" in argv
    assert "stdout_lines" in proof["failed_when"], "an empty checkout fails the provision"
