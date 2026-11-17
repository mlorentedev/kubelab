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
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import jinja2
import pytest
import yaml

from tests.shells import child_env

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
    """`--tags mise` skips tasks without it: a consumer would read an undefined register."""
    tasks = _tasks()
    resolve = tasks[_index("Resolve the node install mise has active")]
    consumers = [t for t in tasks if "block" not in t and "_dev_node_node_where" in str(t) and t is not resolve]
    assert len(consumers) >= 4, "the assert, the entry-point check, the repair and the retired npm install"
    for task in consumers:
        assert tasks.index(resolve) < tasks.index(task), task["name"]
        tags = set(task.get("tags", [])) - {"dev_node"}
        assert tags <= set(resolve["tags"]), f"{task['name']!r} can run without the resolve under {tags}"


# --- the /usr/local/bin wrappers resolve node on every call ------------------
# dotfiles' converge prunes node installs no config pins any more
# (`mise prune --yes --tools`), so the day it bumps NODE_VERSION the old tree is
# gone. A wrapper that exec'd the path the provision saw would point at nothing
# until the next provision, and a non-interactive SSH agent has no other node.

# mise lays tools out differently: node keeps its entry points under `bin/`, the
# aqua `claude` is one binary at the install root. The wrapper asks mise for the
# executable (`mise which <item>`) instead of assuming a layout (#3566).
WRAPPED = {"node": "node", "npm": "node", "npx": "node", "claude": "claude"}
WRAPPER_TASK = "Wrap mise node, npm, npx, and claude into /usr/local/bin for non-interactive SSH tools"


def _render_wrapper(item: str, home: Path) -> str:
    task = _tasks()[_index(WRAPPER_TASK)]
    env = jinja2.Environment(loader=jinja2.FileSystemLoader(str(ROLE / "templates")), undefined=jinja2.StrictUndefined)
    return env.get_template("mise-bin-wrapper.sh.j2").render(item=item, dev_node_home=str(home), **task["vars"])


def test_a_mise_wrapper_names_no_install_path_or_version() -> None:
    for item in WRAPPED:
        rendered = _render_wrapper(item, Path("/home/u"))
        code = "\n".join(ln for ln in rendered.splitlines() if ln.strip() and not ln.lstrip().startswith("#"))
        assert "installs/" not in code, f"the {item} wrapper bakes in an install directory"
        assert not re.search(r"\d+\.\d+\.\d+", code), f"the {item} wrapper bakes in a version"
        assert f'mise" which {item}' in code, f"the {item} wrapper must ask mise where {item} is"
        assert "/bin/" + item not in code, f"the {item} wrapper assumes a bin/ layout the aqua backend does not have"


def _layout(home: Path, item: str, version: str) -> Path:
    """Where mise puts the tool: node's entry points under bin/, claude at the install root."""
    if WRAPPED[item] == "node":
        return home / "installs/node" / version / "bin" / item
    return home / "installs/claude" / version / item


def _install(home: Path, version: str) -> None:
    for item in WRAPPED:
        tool = _layout(home, item, version)
        tool.parent.mkdir(parents=True, exist_ok=True)
        tool.write_text(f'#!/bin/sh\necho {item} {version} "$@"\n', encoding="utf-8", newline="\n")
        tool.chmod(0o755)


def _fake_mise(home: Path) -> None:
    """`mise which <item>` answers the path recorded under <home>/active/<item>; anything else is an error.

    It also talks on stderr, as mise does: only stdout may become the path."""
    mise = home / ".local/bin/mise"
    mise.parent.mkdir(parents=True, exist_ok=True)
    script = (
        f'#!/bin/sh\n[ "$1" = which ] || exit 2\necho "mise: noise" >&2\ncat "{home}/active/$2" 2>/dev/null || exit 1\n'
    )
    mise.write_text(
        script,
        encoding="utf-8",
        newline="\n",
    )
    mise.chmod(0o755)


def _activate(home: Path, version: str) -> None:
    (home / "active").mkdir(exist_ok=True)
    for item in WRAPPED:
        (home / "active" / item).write_text(str(_layout(home, item, version)) + "\n", encoding="utf-8", newline="\n")


def _run(wrapper: Path, home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    """As a non-interactive SSH session runs it: no mise activation, a bare PATH."""
    env = child_env({"HOME": str(home), "PATH": "/usr/bin:/bin"})
    return subprocess.run(
        ["/bin/sh", str(wrapper), *args], env=env, capture_output=True, text=True, encoding="utf-8", check=False
    )


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sh wrappers")
def test_the_wrapper_follows_a_tool_bump_without_a_reprovision(tmp_path: Path) -> None:
    """The consumer is a shell that runs the wrapper after the converge pruned the old install."""
    home = tmp_path / "home"
    _fake_mise(home)
    wrappers = {}
    for item in WRAPPED:
        wrappers[item] = tmp_path / f"wrapper-{item}"
        wrappers[item].write_text(_render_wrapper(item, home), encoding="utf-8", newline="\n")

    _install(home, "1.0.0")
    _activate(home, "1.0.0")
    for item, wrapper in wrappers.items():
        out = _run(wrapper, home, "hi")
        assert (out.returncode, out.stdout.strip()) == (0, f"{item} 1.0.0 hi"), out.stderr

    # The converge bumps the tools and prunes the old trees.
    _install(home, "2.0.0")
    shutil.rmtree(home / "installs/node/1.0.0")
    shutil.rmtree(home / "installs/claude/1.0.0")
    _activate(home, "2.0.0")
    for item, wrapper in wrappers.items():
        out = _run(wrapper, home, "hi")
        assert (out.returncode, out.stdout.strip()) == (0, f"{item} 2.0.0 hi"), out.stderr


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sh wrappers")
@pytest.mark.parametrize("item", list(WRAPPED))
def test_the_wrapper_says_which_tool_mise_does_not_have(tmp_path: Path, item: str) -> None:
    home = tmp_path / "home"
    (home / ".local/bin").mkdir(parents=True)
    mise = home / ".local/bin/mise"
    mise.write_text("#!/bin/sh\necho 'mise ERROR not installed' >&2\nexit 1\n", encoding="utf-8", newline="\n")
    mise.chmod(0o755)
    wrapper = tmp_path / f"wrapper-{item}"
    wrapper.write_text(_render_wrapper(item, home), encoding="utf-8", newline="\n")
    out = _run(wrapper, home, "--version")
    assert out.returncode == 127
    assert f"mise has no {item}" in out.stderr, "a caller must see which tool is missing, not 'No such file'"
