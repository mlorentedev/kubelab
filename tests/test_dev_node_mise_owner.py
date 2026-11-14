"""The dev node's mise config pins only what the dotfiles do not (#3559).

The dotfiles' converge writes `~/.config/mise/conf.d/dotfiles.toml` from its
`versions.conf`: node and python are among the tools it pins (the `# mise: cli`
lines). The role wrote `~/.config/mise/config.toml` with its own node and python,
and mise gives `config.toml` precedence over `conf.d/`. The role's pins won, the
dotfiles installed theirs and then failed its own post-install check:

    failed: after mise install, not running at their pin: node, python

on ace2 (2026-11-14), at the converge's `tools` step, so every step after it
(`lanes`, `git-hooks`, `configs-deploy`) never ran. Two writers of one tool cannot
converge. The dotfiles own node and python; the role asks mise which node is
active and never reads a version from its own defaults.

Go is the role's: the dotfiles' `GO_VERSION` is not a mise pin (it is the
`~/Applications/go-<version>` layout), so nothing else writes `go` to mise.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/dev_node"

# The tools the dotfiles' versions.conf pins for mise, which the role touches.
# Add a name here when the dotfiles take over another tool the role pins.
OWNED_BY_DOTFILES = {"node", "python"}


def _tasks() -> list[dict]:
    tasks: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")):
        tasks.extend([task, *(task.get("block") or [])])
    return tasks


def _index(name: str) -> int:
    (i,) = [i for i, t in enumerate(_tasks()) if t.get("name") == name]
    return i


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _rendered_pins() -> set[str]:
    text = (ROLE / "templates/mise-config.toml.j2").read_text(encoding="utf-8")
    rendered = jinja2.Template(text).render(dev_node_toolchains=_defaults()["dev_node_toolchains"])
    return set(tomllib.loads(rendered)["tools"])


def test_the_rendered_mise_config_pins_nothing_the_dotfiles_own() -> None:
    """What the consumer reads is the rendered file: a tool in it shadows conf.d/."""
    shadowed = _rendered_pins() & OWNED_BY_DOTFILES
    assert not shadowed, f"config.toml wins over the dotfiles' conf.d/, so these pins would shadow theirs: {shadowed}"
    assert _rendered_pins() == {"go"}


def test_the_toolchains_the_role_installs_are_the_ones_it_pins() -> None:
    """A default the template does not render would be installed at mise's latest."""
    assert set(_defaults()["dev_node_toolchains"]) == _rendered_pins()


def test_no_role_file_reads_a_node_or_python_version_from_the_defaults() -> None:
    """A second pin is the bug, whether it lands in the template or in a path."""
    read = re.compile(r"dev_node_toolchains(\.|\[['\"])(" + "|".join(OWNED_BY_DOTFILES) + r")\b")
    offenders = [
        f"{p.relative_to(REPO)}:{n}"
        for p in ROLE.rglob("*")
        if p.is_file()
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1)
        if read.search(line)
    ]
    assert not offenders, f"these read a node/python version the dotfiles own: {offenders}"


def test_node_is_resolved_from_mise_after_the_dotfiles_bootstrap() -> None:
    """On a fresh node it is the bootstrap's `dotf tools sync` that installs node."""
    resolve = _tasks()[_index("Resolve the node install mise has active")]
    assert resolve["ansible.builtin.command"]["cmd"] == "{{ dev_node_home }}/.local/bin/mise where node"
    assert resolve["changed_when"] is False, "a read reports no change"
    assert resolve["check_mode"] is False, "a dry run must still hand the next tasks a path"
    assert resolve["register"] == "_dev_node_node_where"
    bootstrap = _index("Run the dotfiles bootstrap (idempotent, secret-free — see verification.md)")
    assert bootstrap < _tasks().index(resolve)


def test_a_node_mise_cannot_name_stops_the_play_with_the_cause() -> None:
    """`mise where` exits non-zero on a node with none installed: say why, not "no such file"."""
    tasks = _tasks()
    resolve = tasks[_index("Resolve the node install mise has active")]
    require = tasks[_index("Require a node that mise can name")]
    assert resolve["failed_when"] is False, "the read reports; the assert below it fails the play"
    assert tasks.index(resolve) < tasks.index(require)
    assert "_dev_node_node_where.rc == 0" in require["ansible.builtin.assert"]["that"]
    assert "bootstrap" in require["ansible.builtin.assert"]["fail_msg"], "name the owner that installs node"
    assert set(require["tags"]) == set(resolve["tags"]), "an `orca` run must fail here too, not at the wrapper"


def test_every_consumer_of_the_node_path_runs_after_the_resolve_and_carries_its_tags() -> None:
    """`--tags orca` skips untagged-for-it tasks: a consumer would read an undefined register."""
    tasks = _tasks()
    resolve = tasks[_index("Resolve the node install mise has active")]
    consumers = [t for t in tasks if "block" not in t and "_dev_node_node_where" in str(t) and t is not resolve]
    assert len(consumers) >= 4, "the entry-point check, the repair, the npm install and the wrapper"
    for task in consumers:
        assert tasks.index(resolve) < tasks.index(task), task["name"]
        tags = set(task.get("tags", [])) - {"dev_node"}
        assert tags <= set(resolve["tags"]), f"{task['name']!r} can run without the resolve under {tags}"


def test_the_wrapper_and_the_npm_install_resolve_to_the_active_node() -> None:
    """Render the vars the consumers use with a fake mise answer: the path is mise's."""
    active = "/home/u/.local/share/mise/installs/node/24.22.1"
    registered = {"stdout": active + "\n"}
    wrapper = _tasks()[_index("Wrap mise node, npm, npx, and claude into /usr/local/bin for non-interactive SSH tools")]
    npm = _tasks()[_index("Install global agent CLI tools via mise node npm")]
    for raw in (wrapper["vars"]["wrapper_src_dir"], npm["vars"]["_dev_node_mise_node_bin"]):
        assert jinja2.Template(raw).render(_dev_node_node_where=registered) == active + "/bin"
