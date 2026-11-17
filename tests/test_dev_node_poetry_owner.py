"""poetry has one owner on the dev node, and it is the dotfiles (#3577).

The dotfiles' `packages.json` installs poetry as a `uv-tool` (profile `full`) into
`~/.local/bin/poetry`. The role's `drill_runtime.yml` used to probe that binary for
`dev_node_poetry_version` (2.2.1) and, finding the dotfiles' 2.5.1, run
`pipx install --force poetry==2.2.1` over the same path. The next pass ran the
bootstrap, which put 2.5.1 back, and the loop never converged: every provision
reported `changed` (ace2, 2026-11-15, three consecutive passes). Two installers of
one binary cannot both be right. The role installs no poetry; the drills use
whatever version the dotfiles pin, and the role says so when it is missing.

The pipx install an earlier provision left behind is retired once, before the
bootstrap, so the bootstrap's own `~/.local/bin/poetry` is the one that remains.
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


# --- the retirement of the pipx install an earlier provision left ------------

STAT_VENV = "Look for the poetry venv pipx created"
STAT_LINK = "Look at what ~/.local/bin/poetry points to"
RM_LINK = "Retire the ~/.local/bin/poetry link that points into the pipx venv"
RM_VENV = "Retire the pipx poetry venv"


def test_the_pipx_venv_is_looked_for_by_path_without_running_pipx() -> None:
    stat = _by_name(STAT_VENV)["ansible.builtin.stat"]
    assert stat["path"] == PIPX_VENV
    assert _by_name(STAT_VENV)["check_mode"] is False, "a dry run must still see what would be retired"


def test_the_link_is_removed_only_when_it_points_into_the_pipx_venv() -> None:
    """After a pass the bootstrap's uv-tool link may be the one at that path: leave it."""
    stat = _by_name(STAT_LINK)
    assert stat["ansible.builtin.stat"]["path"] == POETRY_LINK
    assert stat["ansible.builtin.stat"]["follow"] is False, "a followed link answers about its target"
    rm = _by_name(RM_LINK)
    assert rm["ansible.builtin.file"] == {"path": POETRY_LINK, "state": "absent"}
    cond = " ".join(rm["when"] if isinstance(rm["when"], list) else [rm["when"]])
    assert "islnk" in cond, "a regular file at that path is not pipx's"
    assert "/.local/share/pipx/venvs/poetry/" in cond, "only a link into the pipx venv is retired"


def test_the_venv_is_removed_only_when_it_exists() -> None:
    rm = _by_name(RM_VENV)
    assert rm["ansible.builtin.file"] == {"path": PIPX_VENV, "state": "absent"}
    assert "exists" in str(rm["when"]), "the venv-exists condition is what makes the second pass `changed=0`"


def test_the_retirement_never_touches_the_uv_tool_poetry() -> None:
    for name in (STAT_VENV, STAT_LINK, RM_LINK, RM_VENV):
        assert UV_TOOL_POETRY not in str(_by_name(name)), f"{name!r} reaches the dotfiles' poetry"
    assert "pipx uninstall" not in " ".join(_command_text(t) for t in _tasks()), (
        "`pipx uninstall` unlinks whatever it finds at ~/.local/bin/poetry, the dotfiles' included"
    )


def test_the_link_goes_before_the_bootstrap_which_puts_the_dotfiles_one_back() -> None:
    """Retiring after the bootstrap would leave a node with no poetry until the next converge."""
    order = [_index(n) for n in (STAT_VENV, STAT_LINK, RM_LINK, RM_VENV)]
    assert order == sorted(order), "look before removing, and the link before the venv it points into"
    assert order[-1] < _index(BOOTSTRAP)
    assert _index(BOOTSTRAP) < _index("Read the poetry version the dev user has")


def test_a_run_that_retires_also_runs_the_bootstrap() -> None:
    """`--tags drill` must not remove poetry and then skip the step that restores it."""
    bootstrap = _by_name(BOOTSTRAP)
    for name in (STAT_VENV, STAT_LINK, RM_LINK, RM_VENV):
        assert set(_by_name(name)["tags"]) <= set(bootstrap["tags"]), f"{name!r} can run without the bootstrap"
    for name in (RM_LINK, RM_VENV):
        assert "dev_node_dotfiles_run_setup" in str(_by_name(name)["when"]), (
            f"{name!r} removes poetry while the bootstrap that restores it is switched off"
        )


# --- the effect: run the real tasks against a stand-in home ------------------
# The tests above read the YAML. What decides whether the dotfiles' poetry survives
# is what Ansible does with those keys, so run them.


def _run_retirement(home: Path, setup: bool = True) -> subprocess.CompletedProcess[str]:
    names = (STAT_VENV, STAT_LINK, RM_LINK, RM_VENV)
    tasks = [t for t in _load("main.yml") if t.get("name") in names]
    assert [t["name"] for t in tasks] == list(names)
    play = [
        {
            "hosts": "localhost",
            "gather_facts": False,
            "connection": "local",
            "vars": {"dev_node_home": str(home), "dev_node_dotfiles_run_setup": setup},
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
def test_a_pipx_poetry_is_retired_once_and_the_second_pass_changes_nothing(tmp_path: Path) -> None:
    home = _host(tmp_path, link_into="pipx")

    first = _run_retirement(home)
    assert first.returncode == 0, first.stdout + first.stderr
    assert not (home / ".local/bin/poetry").is_symlink(), "the link into the pipx venv must go"
    assert not (home / ".local/share/pipx/venvs/poetry").exists()
    assert (home / UV_TOOL_POETRY / "bin/poetry").read_text(encoding="utf-8") == "uv poetry 2.5.1\n"
    assert _changed(first) == 2

    second = _run_retirement(home)
    assert second.returncode == 0, second.stdout + second.stderr
    assert _changed(second) == 0, second.stdout


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_the_dotfiles_link_survives_the_retirement(tmp_path: Path) -> None:
    """The bootstrap already put its link back: only the leftover venv is retired."""
    home = _host(tmp_path, link_into="uv")

    result = _run_retirement(home)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".local/bin/poetry").resolve() == (home / UV_TOOL_POETRY / "bin/poetry").resolve()
    assert not (home / ".local/share/pipx/venvs/poetry").exists()
    assert _changed(result) == 1


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_nothing_is_removed_while_the_bootstrap_that_restores_poetry_is_off(tmp_path: Path) -> None:
    home = _host(tmp_path, link_into="pipx")

    result = _run_retirement(home, setup=False)

    assert result.returncode == 0, result.stdout + result.stderr
    assert (home / ".local/bin/poetry").is_symlink()
    assert (home / ".local/share/pipx/venvs/poetry").exists()
    assert _changed(result) == 0


@needs_ansible
@pytest.mark.allow_host_clients(reason="runs ansible-playbook against localhost and a temporary home")
def test_a_node_that_never_had_pipx_poetry_changes_nothing(tmp_path: Path) -> None:
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)

    result = _run_retirement(home)

    assert result.returncode == 0, result.stdout + result.stderr
    assert _changed(result) == 0
