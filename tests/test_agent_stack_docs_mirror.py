"""The repository's read-only docs (spec AI-012 AC10).

One fetch from the public remote, two root-owned checkouts of `docs/`: the tree the MCP
bridge serves Open WebUI and the copy the agent's sandbox mounts. The script runs here
against a real bare repository standing in for the remote.
"""

from __future__ import annotations

import configparser
import subprocess
from pathlib import Path

import pytest

from tests.test_agent_stack_role import _environment, _resolved, _tasks
from tests.test_agent_stack_vault_mirror import Remote
from tests.test_hermes_vault_sync import BRANCH, HERMES, _git, _git_env

DOCS = HERMES["docs_mirror"]


def _render(name: str, **overrides: object) -> str:
    env = _environment()
    return env.get_template(name).render(**{**_resolved(env), **overrides})


@pytest.fixture
def mirror(tmp_path: Path):
    remote = Remote(tmp_path)
    remote.commit("docs/guide.md", "v1\n")
    remote.commit("apps/api/main.go", "not docs\n")
    mirror_dir, sandbox = tmp_path / "mirror", tmp_path / "sandbox"
    script = tmp_path / "docs-mirror"
    script.write_text(
        _render(
            "docs-mirror.sh.j2",
            agent_stack_docs_mirror=str(mirror_dir),
            agent_stack_docs_sandbox=str(sandbox),
            agent_stack_hermes={**HERMES, "docs_mirror": {**DOCS, "remote": remote.bare.as_uri(), "branch": BRANCH}},
        )
    )
    script.chmod(0o755)
    return remote, mirror_dir / "tree", sandbox, script


def _run(script: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(script)], capture_output=True, text=True, check=False, env=_git_env())


def test_both_trees_hold_the_docs_and_nothing_else_of_the_repository(mirror) -> None:
    _, tree, sandbox, script = mirror
    assert _run(script).returncode == 0
    for root in (tree, sandbox):
        assert (root / "docs/guide.md").read_text() == "v1\n"
        assert not (root / "apps").exists(), "sparse: the rest of the repository is not copied"
        assert not (root / ".git").exists(), "no history, no remote, no config in what is mounted"


def test_the_second_tree_is_written_too_and_a_run_follows_the_remote(mirror) -> None:
    """Both trees come from one index, so the second must be written by `--force`, not by the index."""
    remote, tree, sandbox, script = mirror
    _run(script)
    remote.commit("docs/guide.md", "v2\n")
    assert _run(script).returncode == 0
    assert (tree / "docs/guide.md").read_text() == "v2\n"
    assert (sandbox / "docs/guide.md").read_text() == "v2\n"


def test_anything_written_into_a_tree_is_discarded_and_a_deleted_file_leaves(mirror) -> None:
    remote, tree, sandbox, script = mirror
    remote.commit("docs/old.md", "x\n")
    _run(script)
    (sandbox / "docs/guide.md").write_text("tampered\n")
    (sandbox / "planted.md").write_text("not the docs\n")
    (remote.work / "docs/old.md").unlink()
    _git(remote.work, "commit", "-q", "-am", "drop")
    _git(remote.work, "push", "-q", "origin", f"HEAD:{BRANCH}")
    assert _run(script).returncode == 0
    assert (sandbox / "docs/guide.md").read_text() == "v1\n"
    assert not (sandbox / "planted.md").exists()
    assert not (tree / "docs/old.md").exists() and not (sandbox / "docs/old.md").exists()


def test_an_unreachable_remote_fails_and_keeps_the_last_trees(mirror, tmp_path: Path) -> None:
    _, tree, sandbox, script = mirror
    _run(script)
    (tmp_path / "origin.git").rename(tmp_path / "moved.git")
    assert _run(script).returncode != 0
    assert (tree / "docs/guide.md").exists() and (sandbox / "docs/guide.md").exists()


def test_the_script_carries_no_credential() -> None:
    code = "\n".join(line for line in _render("docs-mirror.sh.j2").splitlines() if not line.lstrip().startswith("#"))
    assert "credential" not in code and "token" not in code.lower()
    assert "core.hooksPath=/dev/null" in code


def _unit(name: str) -> configparser.ConfigParser:
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    parser.optionxform = str  # type: ignore[assignment,method-assign]
    parser.read_string(_render(name))
    return parser


def test_the_unit_runs_as_root_writes_only_the_two_trees_and_pages_on_failure() -> None:
    d = _resolved(_environment())
    unit = _unit("docs-mirror.service.j2")
    service = unit["Service"]
    assert "User" not in service and service["ProtectSystem"] == "strict"
    assert service["ReadWritePaths"].split() == [d["agent_stack_docs_mirror"], d["agent_stack_docs_sandbox"]]
    assert "LoadCredential" not in service, "a public remote needs no credential"
    assert service["UMask"] == "0022", "the bridge's user and the agent read what root writes"
    assert unit["Unit"]["OnFailure"] == "kubelab-notify@%n.service"
    assert _unit("docs-mirror.timer.j2")["Timer"]["OnUnitActiveSec"] == DOCS["interval"]


def test_the_sandbox_copy_is_roots_and_the_bridge_copy_is_in_the_root_only_stack_directory() -> None:
    d = _resolved(_environment())
    assert d["agent_stack_docs_mirror"].startswith(d["agent_stack_dir"].rstrip("/") + "/")
    owned = {
        t["ansible.builtin.file"]["owner"]
        for t in _tasks()
        if (t.get("ansible.builtin.file") or {}).get("path") == "{{ item }}" and "docs mirror" in t["name"]
    }
    assert owned == {"root"}, "the agent can read the docs it is given and cannot edit them"


def test_the_run_is_proved_by_what_both_trees_hold() -> None:
    [proof] = [t for t in _tasks() if t.get("name") == "Verify the docs mirror filled both trees"]
    assert len(proof["loop"]) == 2 and "matched" in proof["failed_when"]
    assert proof["check_mode"] is False and proof["ignore_errors"] == "{{ ansible_check_mode }}"
