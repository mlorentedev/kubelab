"""poetry has one owner on the dev node, and it is the dotfiles (#3577).

The dotfiles' `packages.json` installs poetry as a `uv-tool` (profile `full`) into
`~/.local/bin/poetry`. The role's `drill_runtime.yml` used to probe that binary for
`dev_node_poetry_version` (2.2.1) and, finding the dotfiles' 2.5.1, run
`pipx install --force poetry==2.2.1` over the same path. The next pass ran the
bootstrap, which put 2.5.1 back, and the loop never converged: every provision
reported `changed` (ace2, 2026-11-15, three consecutive passes). Two installers of
one binary cannot both be right. The role installs no poetry; the drills use
whatever version the dotfiles pin, and the role says so when it is missing.

The pipx venv an earlier provision left behind is retired once, after the
bootstrap and only when nothing points into it. The role never touches
`~/.local/bin/poetry`: that link is the dotfiles' to write.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/dev_node"

UV_TOOL_POETRY = ".local/share/uv/tools/poetry"
PIPX_VENV = "{{ dev_node_home }}/.local/share/pipx/venvs/poetry"
POETRY_LINK = "{{ dev_node_home }}/.local/bin/poetry"

COMMANDS = ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell")
INSTALLERS = ("ansible.builtin.pip", "pip", "community.general.pipx", "pipx")
BOOTSTRAP = "Run the dotfiles bootstrap (idempotent, secret-free — see verification.md)"


def _load(name: str) -> list[dict]:
    flat: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks" / name).read_text(encoding="utf-8")):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _tasks() -> list[dict]:
    """Every task of the role in play order: main.yml, then the drill file it imports."""
    return [*_load("main.yml"), *_load("drill_runtime.yml")]


def _role_files() -> list[Path]:
    return [p for p in ROLE.rglob("*") if p.is_file()]


def _by_name(name: str) -> dict:
    (task,) = [t for t in _tasks() if t.get("name") == name]
    return task


def _index(name: str) -> int:
    (i,) = [i for i, t in enumerate(_tasks()) if t.get("name") == name]
    return i


def _command_text(task: dict) -> str:
    for key in COMMANDS:
        body = task.get(key)
        if body is not None:
            return body.get("cmd", "") if isinstance(body, dict) else str(body)
    return ""


# --- the guard: the role installs no poetry ----------------------------------


def test_no_task_installs_poetry() -> None:
    for task in _tasks():
        if "block" in task:
            continue  # its children are listed on their own
        cmd = _command_text(task)
        assert "poetry" not in cmd or "--version" in cmd, f"{task.get('name')!r} runs poetry through a command: {cmd}"
        assert "pipx install" not in cmd and "uv tool install" not in cmd and "pip install" not in cmd, (
            f"{task.get('name')!r} installs a tool with a package manager the dotfiles also use"
        )
        for key in INSTALLERS:
            assert key not in task, f"{task.get('name')!r} installs with {key}"
        apt = task.get("ansible.builtin.apt") or {}
        names = apt.get("name") or []
        names = [names] if isinstance(names, str) else names
        assert "pipx" not in names, "pipx existed to install poetry; nothing else in the role needs it"


def test_the_pinned_version_is_gone_from_every_role_file() -> None:
    for path in _role_files():
        assert "dev_node_poetry_version" not in path.read_text(encoding="utf-8"), (
            f"{path.relative_to(REPO)} still reads a poetry pin the dotfiles' pin shadows"
        )


def test_poetry_is_still_exposed_to_non_interactive_sessions() -> None:
    """The wrapper reaches the dotfiles' binary; only its installer moved."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    assert "poetry" in defaults["dev_node_local_bin_wrapped"]


def test_a_node_without_poetry_stops_the_play_with_the_cause() -> None:
    """The drills run `poetry run toolkit`: say who installs it instead of failing mid-drill."""
    probe = _by_name("Read the poetry version the dev user has")
    assert probe["register"] == "_dev_node_poetry"
    assert probe["failed_when"] is False, "the read reports; the assert below it fails the play"
    assert probe["check_mode"] is False
    require = _by_name("The dev user has the poetry the dotfiles install")
    assert _index(probe["name"]) < _index(require["name"])
    that = require["ansible.builtin.assert"]["that"]
    assert "_dev_node_poetry.rc == 0" in " ".join(that if isinstance(that, list) else [that])
    msg = require["ansible.builtin.assert"]["fail_msg"]
    assert "dotf converge" in msg and "dotfiles" in msg, "name the owner that installs poetry"
    assert set(require["tags"]) == set(probe["tags"])


# --- the retirement of the pipx venv an earlier provision left ----------------

STAT_VENV = "Look for the poetry venv pipx created"
STAT_LINK = "Look at what ~/.local/bin/poetry points to"
RM_VENV = "Retire the pipx poetry venv once nothing points into it"


def test_the_pipx_venv_is_looked_for_by_path_without_running_pipx() -> None:
    stat = _by_name(STAT_VENV)
    assert stat["ansible.builtin.stat"]["path"] == PIPX_VENV
    assert stat["check_mode"] is False, "a dry run must still see what would be retired"


def test_the_venv_goes_only_when_it_exists_and_no_link_points_into_it() -> None:
    """While the link still points into the venv, removing it would leave a node with no poetry."""
    link = _by_name(STAT_LINK)
    assert link["ansible.builtin.stat"]["path"] == POETRY_LINK
    assert link["ansible.builtin.stat"]["follow"] is False, "a followed link answers about its target"
    rm = _by_name(RM_VENV)
    assert rm["ansible.builtin.file"] == {"path": PIPX_VENV, "state": "absent"}
    cond = " ".join(rm["when"])
    assert "exists" in cond, "the venv-exists condition is what makes the second pass `changed=0`"
    assert "islnk" in cond and "/.local/share/pipx/venvs/poetry/" in cond


def test_the_role_never_touches_the_poetry_link_or_the_uv_tool() -> None:
    """Whatever sits at ~/.local/bin/poetry is the dotfiles' to write."""
    for task in _tasks():
        for key in ("ansible.builtin.file", "file"):
            body = task.get(key)
            if body is not None:
                assert body.get("path") != POETRY_LINK, f"{task.get('name')!r} writes the poetry link"
    for name in (STAT_VENV, STAT_LINK, RM_VENV):
        assert UV_TOOL_POETRY not in str(_by_name(name)), f"{name!r} reaches the dotfiles' poetry"


def test_the_venv_is_retired_after_the_bootstrap_has_had_its_turn() -> None:
    """Before it, the link may still point into the venv; after it, the dotfiles' link is the one there."""
    order = [_index(n) for n in (STAT_VENV, STAT_LINK, RM_VENV)]
    assert order == sorted(order), "look before removing"
    assert _index(BOOTSTRAP) < order[0]
    assert order[-1] < _index("Read the poetry version the dev user has")


def test_a_run_that_retires_also_runs_the_bootstrap() -> None:
    """`--tags dotfiles` runs both, so the link the retirement reads is the bootstrap's."""
    bootstrap = _by_name(BOOTSTRAP)
    for name in (STAT_VENV, STAT_LINK, RM_VENV):
        assert set(_by_name(name)["tags"]) <= set(bootstrap["tags"]), f"{name!r} can run without the bootstrap"


# --- the effect: run the real tasks against a stand-in home ------------------
# The tests above read the YAML. What decides whether the dotfiles' poetry survives
# is what Ansible does with those keys, so run them.


def _run_retirement(home: Path) -> subprocess.CompletedProcess[str]:
    names = (STAT_VENV, STAT_LINK, RM_VENV)
    tasks = [t for t in _load("main.yml") if t.get("name") in names]
    assert [t["name"] for t in tasks] == list(names)
    play = [
        {
            "hosts": "localhost",
            "gather_facts": False,
            "connection": "local",
            "vars": {"dev_node_home": str(home)},
            "tasks": tasks,
        }
    ]
    playbook = home.parent / "retire.yml"
    playbook.write_text(yaml.safe_dump(play), encoding="utf-8", newline="\n")
    env = {**os.environ, "ANSIBLE_LOCALHOST_WARNING": "False", "ANSIBLE_NOCOLOR": "1", "ANSIBLE_FORCE_COLOR": "0"}
    return subprocess.run(
        ["ansible-playbook", str(playbook), "-i", "localhost,"],
        cwd=home.parent,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _changed(result: subprocess.CompletedProcess[str]) -> int:
    (line,) = [ln for ln in result.stdout.splitlines() if ln.startswith("localhost") and "changed=" in ln]
    return int(line.split("changed=")[1].split()[0])


def _host(tmp_path: Path, *, link_into: str | None) -> Path:
    """A dev user's home with a pipx poetry venv and, optionally, a poetry link into `pipx` or `uv`."""
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    pipx_bin = home / ".local/share/pipx/venvs/poetry/bin"
    pipx_bin.mkdir(parents=True)
    (pipx_bin / "poetry").write_text("pipx poetry 2.2.1\n", encoding="utf-8", newline="\n")
    uv_bin = home / UV_TOOL_POETRY / "bin"
    uv_bin.mkdir(parents=True)
    (uv_bin / "poetry").write_text("uv poetry 2.5.1\n", encoding="utf-8", newline="\n")
    if link_into == "pipx":
        (home / ".local/bin/poetry").symlink_to(pipx_bin / "poetry")
    elif link_into == "uv":
        (home / ".local/bin/poetry").symlink_to(uv_bin / "poetry")
    return home


needs_ansible = pytest.mark.skipif(
    shutil.which("ansible-playbook") is None or sys.platform == "win32",
    reason="ansible-playbook not on PATH (no Windows controller): the retirement was NOT executed",
)


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_the_venv_is_retired_once_the_bootstrap_has_replaced_the_link(tmp_path: Path) -> None:
    home = _host(tmp_path, link_into="uv")

    first = _run_retirement(home)
    assert first.returncode == 0, first.stdout + first.stderr
    assert not (home / ".local/share/pipx/venvs/poetry").exists()
    assert (home / ".local/bin/poetry").resolve() == (home / UV_TOOL_POETRY / "bin/poetry").resolve()
    assert (home / UV_TOOL_POETRY / "bin/poetry").read_text(encoding="utf-8") == "uv poetry 2.5.1\n"
    assert _changed(first) == 1

    second = _run_retirement(home)
    assert second.returncode == 0, second.stdout + second.stderr
    assert _changed(second) == 0, second.stdout


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_the_venv_stays_while_the_link_still_points_into_it(tmp_path: Path) -> None:
    """A bootstrap that stopped early leaves the pipx poetry as the only one: do not remove it."""
    home = _host(tmp_path, link_into="pipx")

    result = _run_retirement(home)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".local/bin/poetry").resolve() == (home / ".local/share/pipx/venvs/poetry/bin/poetry").resolve()
    assert (home / ".local/share/pipx/venvs/poetry/bin/poetry").exists()
    assert _changed(result) == 0


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_a_node_that_never_had_pipx_poetry_changes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)

    result = _run_retirement(home)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _changed(result) == 0


# --- the assert that replaced the install, run for real -----------------------


def _run_assert(home: Path) -> subprocess.CompletedProcess[str]:
    names = ("Read the poetry version the dev user has", "The dev user has the poetry the dotfiles install")
    tasks = [{k: v for k, v in t.items() if k not in ("become", "become_user")} for t in _load("drill_runtime.yml")]
    tasks = [t for t in tasks if t.get("name") in names]
    assert [t["name"] for t in tasks] == list(names)
    play = [
        {
            "hosts": "localhost",
            "gather_facts": False,
            "connection": "local",
            "vars": {"dev_node_home": str(home)},
            "tasks": tasks,
        }
    ]
    playbook = home.parent / "assert.yml"
    playbook.write_text(yaml.safe_dump(play), encoding="utf-8", newline="\n")
    env = {**os.environ, "ANSIBLE_LOCALHOST_WARNING": "False", "ANSIBLE_NOCOLOR": "1", "ANSIBLE_FORCE_COLOR": "0"}
    return subprocess.run(
        ["ansible-playbook", str(playbook), "-i", "localhost,"],
        cwd=home.parent,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_a_node_without_poetry_fails_the_play_naming_the_dotfiles(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)

    result = _run_assert(home)

    assert result.returncode != 0, result.stdout
    assert "dotf converge" in result.stdout + result.stderr


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_a_node_with_the_dotfiles_poetry_passes_whatever_its_version(tmp_path: Path) -> None:
    """The pin is gone: any version the dotfiles install is the right one."""
    home = tmp_path / "home"
    poetry = home / ".local/bin/poetry"
    poetry.parent.mkdir(parents=True)
    poetry.write_text('#!/bin/sh\necho "Poetry (version 9.9.9)"\n', encoding="utf-8", newline="\n")
    poetry.chmod(0o755)

    result = _run_assert(home)

    assert result.returncode == 0, result.stdout + result.stderr
