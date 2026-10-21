"""`make provision` refuses a checkout that is behind origin/master (OPS-041, #2441).

On 2026-10-17 `make provision NODE=bee ENV=prod TAGS=gitea` ran three times from
a branch that predated #2425 and put the Beelink runner back on
`gitea/act_runner:0.2.13`. Nothing failed: Ansible rendered what the branch
declared. The guard compares the checkout with master on the paths an Ansible run
renders, with real git repositories rather than a faked answer, because the
three-dot range is the whole behaviour.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import typer

from toolkit.cli import infra
from toolkit.features import generator_ansible, provision_freshness

_ROOT = Path(__file__).resolve().parents[1]


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout


def _commit(repo: Path, relpath: str, text: str) -> None:
    path = repo / relpath
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    _git(repo, "add", relpath)
    _git(repo, "commit", "-q", "-m", f"change {relpath}")


@pytest.fixture
def clone(tmp_path: Path) -> Path:
    """A clone of an origin whose master later moves; the clone starts on a branch of the old master."""
    origin = tmp_path / "origin"
    origin.mkdir()
    _git(origin, "init", "-q", "-b", "master")
    _commit(origin, "infra/ansible/roles/runner/defaults/main.yml", "image: act_runner:0.2.13\n")
    work = tmp_path / "work"
    _git(tmp_path, "clone", "-q", str(origin), str(work))
    _git(work, "checkout", "-q", "-b", "feat/old-branch")
    return work


def _advance_master(work: Path, relpath: str, text: str) -> None:
    origin = Path(_git(work, "remote", "get-url", "origin").strip())
    _commit(origin, relpath, text)


def test_a_branch_behind_on_a_rendered_role_is_named(clone: Path) -> None:
    _advance_master(clone, "infra/ansible/roles/runner/defaults/main.yml", "image: runner:4.1.0\n")
    assert provision_freshness.paths_behind_master(clone) == ["infra/ansible/roles/runner/defaults/main.yml"]


def test_a_branch_behind_on_the_values_is_named(clone: Path) -> None:
    _advance_master(clone, "infra/config/values/common.yaml", "networking: {}\n")
    assert provision_freshness.paths_behind_master(clone) == ["infra/config/values/common.yaml"]


def test_a_branch_behind_on_the_inventory_generator_is_named(clone: Path) -> None:
    _advance_master(clone, "toolkit/features/generator_ansible.py", "HOST_VARS = ['ssh_lan_jump_targets']\n")
    assert provision_freshness.paths_behind_master(clone) == ["toolkit/features/generator_ansible.py"]


def test_a_change_to_something_ansible_does_not_render_is_not_a_reason_to_refuse(clone: Path) -> None:
    _advance_master(clone, "docs/lessons/x.md", "unrelated\n")
    assert provision_freshness.paths_behind_master(clone) == []


def test_a_branch_that_merged_master_passes(clone: Path) -> None:
    _advance_master(clone, "infra/ansible/roles/runner/defaults/main.yml", "image: runner:4.1.0\n")
    _git(clone, "fetch", "-q", "origin", "master")
    _git(clone, "merge", "-q", "--no-edit", "origin/master")
    assert provision_freshness.paths_behind_master(clone) == []


def test_a_branch_with_its_own_unmerged_role_change_passes(clone: Path) -> None:
    _commit(clone, "infra/ansible/roles/runner/tasks/main.yml", "- debug: {}\n")
    assert provision_freshness.paths_behind_master(clone) == []


def test_a_checkout_that_cannot_be_compared_is_an_error_not_a_pass(tmp_path: Path) -> None:
    with pytest.raises(provision_freshness.FreshnessError):
        provision_freshness.paths_behind_master(tmp_path)


def test_the_refusal_names_the_files_the_cause_and_the_way_out() -> None:
    message = provision_freshness.refusal_message(["infra/ansible/roles/runner/defaults/main.yml"])
    assert "infra/ansible/roles/runner/defaults/main.yml" in message
    assert "WHY:" in message
    assert "git merge origin/master" in message
    assert "FORCE=1" in message


@pytest.fixture
def calls(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> list[tuple[str, Any]]:
    """Records generate and ansible-playbook; the guard's git answer is set per test."""
    (tmp_path / "playbooks").mkdir()
    (tmp_path / "playbooks" / "provision-bee.yml").write_text("---\n")
    (tmp_path / "generated" / "prod").mkdir(parents=True)
    (tmp_path / "generated" / "prod" / "hosts.yml").write_text("---\n")
    monkeypatch.setattr(infra, "settings", SimpleNamespace(ansible_dir=tmp_path))
    log: list[tuple[str, Any]] = []

    def fake_generate(env: str, bootstrap: bool = False, transport: str = "mesh") -> dict[str, Any]:
        log.append(("generate", env))
        return {"success": True, "files": []}

    def fake_run(cmd: str, **_kwargs: Any) -> SimpleNamespace:
        log.append(("ansible-playbook", cmd))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(generator_ansible.ansible_generator, "generate", fake_generate)
    monkeypatch.setattr(infra.command, "run", fake_run)
    return log


def _behind(monkeypatch: pytest.MonkeyPatch, files: list[str]) -> None:
    monkeypatch.setattr(provision_freshness, "paths_behind_master", lambda *_a, **_k: files)


def _run(**overrides: Any) -> None:
    kwargs: dict[str, Any] = {
        "playbook": "provision-bee",
        "env": "prod",
        "limit": None,
        "tags": None,
        "check": False,
        "become_ask_pass": False,
        "extra_vars": None,
        "bootstrap": False,
        "transport": "mesh",
        "skip_generate": False,
        "require_fresh": True,
        "force": False,
    }
    kwargs.update(overrides)
    infra.ansible_run(**kwargs)


def test_a_stale_checkout_stops_before_the_inventory_and_the_playbook(
    calls: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    _behind(monkeypatch, ["infra/ansible/roles/runner/defaults/main.yml"])
    with pytest.raises(typer.Exit) as exited:
        _run()
    assert exited.value.exit_code == 1
    assert calls == []


def test_force_runs_a_stale_checkout(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    _behind(monkeypatch, ["infra/ansible/roles/runner/defaults/main.yml"])
    _run(force=True)
    assert [name for name, _ in calls] == ["generate", "ansible-playbook"]


def test_a_current_checkout_runs(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    _behind(monkeypatch, [])
    _run()
    assert [name for name, _ in calls] == ["generate", "ansible-playbook"]


def test_a_dry_run_changes_nothing_so_it_is_not_refused(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    _behind(monkeypatch, ["infra/ansible/roles/runner/defaults/main.yml"])
    _run(check=True)
    assert [name for name, _ in calls] == ["generate", "ansible-playbook"]


def test_a_run_that_did_not_ask_for_the_guard_is_not_checked(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    _behind(monkeypatch, ["infra/ansible/roles/runner/defaults/main.yml"])
    _run(require_fresh=False)
    assert [name for name, _ in calls] == ["generate", "ansible-playbook"]


def _unreachable(*_a: Any, **_k: Any) -> list[str]:
    raise provision_freshness.FreshnessError("git fetch: could not resolve host")


def test_a_comparison_that_fails_refuses_rather_than_assuming_current(
    calls: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(provision_freshness, "paths_behind_master", _unreachable)
    with pytest.raises(typer.Exit):
        _run()
    assert calls == []


def test_force_runs_when_the_comparison_fails(calls: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(provision_freshness, "paths_behind_master", _unreachable)
    _run(force=True)
    assert [name for name, _ in calls] == ["generate", "ansible-playbook"]


def _provision_commands(*extra: str) -> str:
    done = subprocess.run(
        ["make", "-n", "provision", "NODE=bee", "ENV=prod", *extra],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    commands = "\n".join(line for line in done.stdout.splitlines() if "infra ansible run" in line)
    assert commands, "no `infra ansible run` line in the dry run, so a negative check would pass on nothing"
    return commands


def test_make_provision_always_asks_for_the_guard() -> None:
    commands = _provision_commands()
    assert "--require-fresh" in commands
    assert "--force" not in commands


@pytest.mark.parametrize("value", ["0", ""])
def test_force_zero_or_empty_does_not_override(value: str) -> None:
    assert "--force" not in _provision_commands(f"FORCE={value}")


def test_force_one_overrides() -> None:
    commands = _provision_commands("FORCE=1")
    assert "--require-fresh" in commands
    assert "--force" in commands


def _deploy_commands(*extra: str) -> str:
    done = subprocess.run(
        ["make", "-n", "deploy", "TARGET=vps", "ENV=prod", *extra],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr
    commands = "\n".join(line for line in done.stdout.splitlines() if "infra ansible run" in line)
    assert commands, "no `infra ansible run` line in the dry run, so a negative check would pass on nothing"
    return commands


def test_make_deploy_always_asks_for_the_guard() -> None:
    commands = _deploy_commands()
    assert "--require-fresh" in commands
    assert "--force" not in commands


@pytest.mark.parametrize("value", ["0", ""])
def test_deploy_force_zero_or_empty_does_not_override(value: str) -> None:
    assert "--force" not in _deploy_commands(f"FORCE={value}")


def test_deploy_force_one_overrides() -> None:
    commands = _deploy_commands("FORCE=1")
    assert "--require-fresh" in commands
    assert "--force" in commands
