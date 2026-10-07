"""The agent commits only inside its own vault zone (ADR-068 D4, spec AI-009 AC6).

The hook runs in a real temporary git repository, through `core.hooksPath` as
the clone will use it, so these cases are git's own verdicts, not a reading of
the script. A hook the committer can skip (`--no-verify`, another hooksPath) is
a guard against the agent's mistakes, as it was on NaN; it is not the boundary.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
COMMON = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text())
ZONE = COMMON["apps"]["services"]["ai"]["hermes_kubelab"]["vault_zone"]


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=False)


def _hook(hooks: Path, zone: str) -> Path:
    hooks.mkdir()
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    hook = hooks / "pre-commit"
    template = env.get_template("pre-commit-zone.sh.j2")
    hook.write_text(template.render(ansible_managed="managed", agent_stack_vault_zone=zone))
    hook.chmod(0o755)
    return hook


def _vault(tmp_path: Path, zone: str) -> Path:
    hooks = tmp_path / "hooks"
    _hook(hooks, zone)
    repo = tmp_path / "vault"
    repo.mkdir()
    for args in (
        ("init", "-q", "-b", "main"),
        ("config", "user.email", "agent@example.test"),
        ("config", "user.name", "agent"),
        ("config", "commit.gpgsign", "false"),
        ("config", "core.hooksPath", str(hooks)),
    ):
        _git(repo, *args)
    for path in ("10_projects/kubelab/roadmap.md", f"{zone}/notes.md"):
        (repo / path).parent.mkdir(parents=True, exist_ok=True)
        (repo / path).write_text("seed\n")
    _git(repo, "add", "-A")
    assert _git(repo, "commit", "-q", "--no-verify", "-m", "seed").returncode == 0
    return repo


@pytest.fixture
def vault(tmp_path: Path) -> Path:
    return _vault(tmp_path, ZONE)


def _commit(repo: Path) -> int:
    _git(repo, "add", "-A")
    return _git(repo, "commit", "-q", "-m", "change").returncode


def _write(repo: Path, path: str) -> None:
    (repo / path).parent.mkdir(parents=True, exist_ok=True)
    (repo / path).write_text("change\n")


def test_a_change_inside_the_zone_is_accepted(vault: Path) -> None:
    _write(vault, f"{ZONE}/notes.md")
    _write(vault, f"{ZONE}/jobs/new file.md")
    assert _commit(vault) == 0


def test_a_change_outside_the_zone_is_refused(vault: Path) -> None:
    _write(vault, "10_projects/kubelab/roadmap.md")
    assert _commit(vault) != 0


def test_one_path_outside_refuses_the_whole_commit(vault: Path) -> None:
    _write(vault, f"{ZONE}/notes.md")
    _write(vault, "10_projects/kubelab/roadmap.md")
    assert _commit(vault) != 0


def test_a_deletion_outside_the_zone_is_refused(vault: Path) -> None:
    (vault / "10_projects/kubelab/roadmap.md").unlink()
    assert _commit(vault) != 0


def test_moving_a_file_into_the_zone_is_refused(vault: Path) -> None:
    """A rename is a deletion outside the zone; git must not fold it into one path."""
    assert _git(vault, "mv", "10_projects/kubelab/roadmap.md", f"{ZONE}/roadmap.md").returncode == 0
    assert _commit(vault) != 0


def test_a_sibling_that_shares_the_prefix_is_outside(vault: Path) -> None:
    _write(vault, f"{ZONE}-other/notes.md")
    assert _commit(vault) != 0


def test_a_newline_inside_an_in_zone_path_is_one_path(vault: Path) -> None:
    """Paths are never split on newlines: git judges each one whole."""
    _write(vault, f"{ZONE}/a\nb.md")
    assert _commit(vault) == 0


def test_a_path_that_is_only_a_newline_is_outside(vault: Path) -> None:
    """A line-based parse reads it as an empty line and drops it unjudged."""
    _write(vault, "\n")
    assert _commit(vault) != 0


def test_a_failing_git_refuses_the_commit(tmp_path: Path) -> None:
    """With git piped into the parse, its failure read as "nothing staged" and the
    commit went through: the shell judges a pipeline by its last command."""
    hook = _hook(tmp_path / "hooks", ZONE)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "git").write_text("#!/bin/sh\nexit 128\n")
    (bin_dir / "git").chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}"}
    assert subprocess.run([str(hook)], env=env, cwd=tmp_path, capture_output=True, check=False).returncode != 0


def test_the_zone_comes_from_the_ssot() -> None:
    source = (ROLE / "templates/pre-commit-zone.sh.j2").read_text()
    assert "{{ agent_stack_vault_zone }}" in source
    assert "hermes-kubelab" not in source
    from tests.test_agent_egress import _role_vars

    assert _role_vars()["agent_stack_vault_zone"] == "{{ config.apps.services.ai.hermes_kubelab.vault_zone }}"


def test_the_agent_cannot_edit_the_hook() -> None:
    tasks = yaml.safe_load((ROLE / "tasks/vault_zone.yml").read_text())
    renders = [t for t in tasks if (t.get("ansible.builtin.template") or {}).get("src") == "pre-commit-zone.sh.j2"]
    assert len(renders) == 1
    spec = renders[0]["ansible.builtin.template"]
    assert spec["owner"] == "root" and spec["mode"] == "0755"
    assert spec["dest"] == "{{ agent_stack_vault_hooks }}/pre-commit"
    dirs = [t for t in tasks if (t.get("ansible.builtin.file") or {}).get("path") == "{{ agent_stack_vault_hooks }}"]
    assert len(dirs) == 1
    assert dirs[0]["ansible.builtin.file"]["owner"] == "root", "an agent-owned parent can swap the hook"
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    assert not defaults["agent_stack_vault_hooks"].startswith("/home/")
