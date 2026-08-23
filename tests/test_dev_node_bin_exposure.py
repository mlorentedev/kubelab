"""The mise toolchain reaches non-interactive SSH through wrappers, not symlinks.

Non-interactive sessions (Orca ADE's remote relay, agent harnesses, CI over SSH)
skip `/etc/profile.d` and `~/.bashrc`, so the pinned node toolchain has to be on
the plain `$PATH`. The role used to symlink four names into `/usr/local/bin`.

That measured broken on ace2, 2026-08-23 — the first time it ran against the
node, because the node was powered off when it merged:

    $ npm --version
    Error: Cannot find module '/usr/local/lib/node_modules/npm/bin/npm-cli.js'

mise does not install `bin/npm` as a binary. It installs a bash script that
locates npm's JS relative to itself via `dirname "${BASH_SOURCE[0]}"`, and the
`pwd -P` in that script normalises the directory without resolving a symlinked
file. Reached through the symlink it computed `plugin_dir=/usr/local`.

`npx` came out of the same loop working, and that is the part worth pinning:
mise packages *that* entry as a symlink to `npx-cli.js`, so resolution landed on
a real JS file. One task, one loop, opposite outcomes, decided by how upstream
happened to package each name. A mechanism whose correctness depends on that is
one nobody can verify by reading it.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/dev_node"

WRAPPED = ["node", "npm", "npx", "claude"]
MISE_NODE_BIN = "/home/manu/.local/share/mise/installs/node/24.19.0/bin"
LOCAL_BIN = "/home/manu/.local/bin"
DEFAULTS = ROLE / "defaults/main.yml"


def _tasks() -> list[dict]:
    """Every task in the role, including those nested in a block."""
    flat: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text()):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _exposure_task() -> dict:
    for task in _tasks():
        if task.get("loop") == WRAPPED:
            return task
    raise AssertionError(f"no task loops over {WRAPPED} to expose them on /usr/local/bin")


def test_the_toolchain_is_exposed_by_wrapper_not_by_symlink() -> None:
    """A symlink hands the tool a $0 that lies about where it lives.

    mise's `bin/npm` reads its own path to find npm's JS. Through a symlink that
    path is `/usr/local/bin/npm`, so it searches `/usr/local/lib/node_modules`
    and fails. `exec`ing the real path makes `$0` the real path.
    """
    task = _exposure_task()
    assert "ansible.builtin.template" in task or "template" in task, (
        "the four names must be exposed with a rendered wrapper. `file: state=link` "
        "is what broke npm: mise's bin/npm resolves its JS relative to its own "
        "invocation path, and a symlink makes that path /usr/local/bin."
    )
    assert not any((task.get(k) or {}).get("state") == "link" for k in ("file", "ansible.builtin.file")), (
        "state: link is the mechanism this replaced"
    )


def test_the_wrapper_does_not_write_through_the_old_symlink() -> None:
    """`follow: true` would corrupt the very file the wrapper needs.

    The broken symlinks are already on disk from the previous approach, so on
    every node provisioned before this change `dest` IS a symlink into the mise
    install. Following it writes the wrapper over mise's own `bin/npm`, whose
    content is what the wrapper execs.
    """
    task = _exposure_task()
    spec = task.get("template") or task.get("ansible.builtin.template")
    assert spec.get("follow") is False, (
        "the template must set `follow: false`; the destination is an existing "
        "symlink into the mise install on every already-provisioned node, and "
        "following it overwrites mise's own bin/npm with this wrapper"
    )
    assert spec.get("mode") == "0755", "a wrapper that is not executable is not on PATH in any useful sense"


# --- ~/.local/bin: installed and invisible ---------------------------------
# A non-interactive SSH session's PATH is /etc/environment verbatim. Measured on
# ace2 2026-08-23: pam_env.so is in sshd's stack and the session PATH matches
# that file character for character. ~/.local/bin is not in it, so `dotf`,
# `hive` and `hive-vault` existed on the node and did not exist for a remote
# agent — an interactive login found them and reported everything fine.


def _local_bin_task() -> dict:
    declared = yaml.safe_load(DEFAULTS.read_text())["dev_node_local_bin_wrapped"]
    for task in _tasks():
        if task.get("loop") == "{{ dev_node_local_bin_wrapped }}":
            return task
    raise AssertionError(f"no task exposes the ~/.local/bin tools {declared} on /usr/local/bin")


def test_the_doctrine_cli_is_reachable_from_a_non_interactive_session() -> None:
    """`dotf` is what the project's own standing orders tell every agent to run.

    `dotf pr triage-queue` and `dotf secrets run` are instructions given to every
    agent in this repo. An agent driven over non-interactive SSH got "command not
    found" for both, and nothing reported it, because a human checking by hand
    logs in interactively and sees the tool.
    """
    declared = yaml.safe_load(DEFAULTS.read_text())["dev_node_local_bin_wrapped"]
    assert "dotf" in declared, (
        "dotf must be exposed: the standing orders instruct every agent to run it, "
        "and a remote agent's PATH does not include ~/.local/bin"
    )
    assert {"hive", "hive-vault"} <= set(declared), "the vault MCP entrypoints must be reachable too"


def test_the_local_bin_wrappers_use_the_same_mechanism_and_guard() -> None:
    """Same template, same `follow: false`, different source directory.

    Two exposure tasks with two mechanisms would mean two things to keep correct.
    `follow: false` matters here for the same reason it does above — these
    destinations may already hold a symlink from an earlier approach.
    """
    task = _local_bin_task()
    spec = task.get("template") or task.get("ansible.builtin.template")
    assert spec, "the ~/.local/bin tools must be exposed with the same rendered wrapper"
    assert spec.get("src") == "mise-bin-wrapper.sh.j2", "one template, not a second mechanism"
    assert spec.get("follow") is False, "must not write through an existing symlink at the destination"
    assert spec.get("mode") == "0755"
    assert (task.get("vars") or {}).get("wrapper_src_dir", "").endswith("/.local/bin"), (
        "this loop's source directory is the developer user's ~/.local/bin"
    )


def test_local_bin_is_not_appended_to_the_system_path_instead() -> None:
    """The rejected alternative, pinned so it is not reintroduced as a shortcut.

    Appending ~/.local/bin to /etc/environment would expose all of these in one
    line — and put a user-writable directory on root's PATH. The wrapper list is
    also what a reviewer reads to know what /usr/local/bin exposes.
    """
    text = (ROLE / "tasks/main.yml").read_text()
    code = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert not any("/etc/environment" in ln for ln in code), (
        "no task may write /etc/environment: that places a user-writable directory "
        "on root's PATH, which the per-tool wrapper exists to avoid"
    )


def test_the_template_renders_for_both_source_directories() -> None:
    """One template, two `wrapper_src_dir` values — render both, do not assume."""
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    template = env.get_template("mise-bin-wrapper.sh.j2")
    declared = yaml.safe_load(DEFAULTS.read_text())["dev_node_local_bin_wrapped"]

    for src_dir, items in ((MISE_NODE_BIN, WRAPPED), (LOCAL_BIN, declared)):
        for item in items:
            rendered = template.render(item=item, wrapper_src_dir=src_dir)
            code = [ln for ln in rendered.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
            assert any(f'exec "{src_dir}/{item}"' in ln for ln in code), (
                f"{item} must exec {src_dir}/{item}; executable lines were {code}"
            )
            assert any('"$@"' in ln for ln in code), f"the {item} wrapper must forward its arguments"
            assert not any("/usr/local/lib/node_modules" in ln for ln in code), (
                "no executable line may reference the path the broken symlink resolved to"
            )
