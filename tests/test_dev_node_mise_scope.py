"""The dev node's provision installs its own toolchains and nothing else (#2815).

The role renders `~/.config/mise/config.toml` with node, go and python, then ran a
bare `mise install`. mise installs every tool in every config it reads, and on
ace2 it also reads the operator's dotfiles in `~/.config/mise/conf.d/`: 42 tools,
two of them at `@latest`. Behind the lab edge, on 2026-10-29, three of those
(about 450 MB) ran into mise's own 30-minute download limit and failed the
provision before `agent_stack`. The dotfiles' tools are the dotfiles deploy's to
install. The role names its own.

The same task reported `changed` on every pass: its guard read "installing" in
mise's output, and mise prints "installing N tools" when all N are already
installed. It now installs only what `mise ls --missing` names.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/dev_node"


def _tasks() -> list[dict]:
    tasks: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")):
        tasks.extend([task, *(task.get("block") or [])])
    return tasks


def _mise(verb: str) -> dict:
    (task,) = [t for t in _tasks() if f"mise {verb}" in str(t.get("ansible.builtin.command", ""))]
    return task


def _install_task() -> dict:
    return _mise("install")


def _render(text: str) -> str:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    return jinja2.Template(text).render(dev_node_home="/home/u", dev_node_toolchains=defaults["dev_node_toolchains"])


def test_the_install_names_exactly_the_toolchains_the_role_pins() -> None:
    """The tools the install and the read name are the ones the rendered config pins:
    a key the template does not render would be installed at whatever mise resolves."""
    binary, verb, *tools = _render(_install_task()["ansible.builtin.command"]["cmd"]).split()
    assert (binary, verb) == ("/home/u/.local/bin/mise", "install")
    assert tools, "a bare `mise install` installs every config's tools, the dotfiles' included"
    pinned = tomllib.loads(_render((ROLE / "templates/mise-config.toml.j2").read_text(encoding="utf-8")))["tools"]
    assert set(tools) == set(pinned) == {"node", "go", "python"}
    assert _render(_mise("ls --missing")["ansible.builtin.command"]["cmd"]).split()[3:] == tools


def test_the_install_runs_only_for_a_missing_toolchain() -> None:
    """A dry run reads what is missing, and the read never reports a change."""
    read, install = _mise("ls --missing"), _install_task()
    assert read["changed_when"] is False and read["check_mode"] is False
    assert read["register"] in install["when"]
    assert "changed_when" not in install, "mise's prose cannot say what changed"
    assert _tasks().index(read) < _tasks().index(install)
