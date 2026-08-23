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


def test_the_rendered_wrapper_execs_the_mise_path_not_the_public_one() -> None:
    """Render it — the bug was in what the path resolved to, not in the YAML."""
    env = Environment(loader=FileSystemLoader(str(ROLE / "templates")), undefined=StrictUndefined)
    template = env.get_template("mise-bin-wrapper.sh.j2")

    for item in WRAPPED:
        rendered = template.render(
            item=item,
            dev_node_home="/home/manu",
            dev_node_toolchains={"node": "24.19.0"},
        )
        # Comments only, stripped deliberately: the template EXPLAINS the broken
        # path, so a scan of the whole file matches the prose and says nothing
        # about the mechanism. This test caught itself doing exactly that.
        code = [ln for ln in rendered.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]

        assert any(f'exec "{MISE_NODE_BIN}/{item}"' in ln for ln in code), (
            f"the {item} wrapper must exec the mise install path; that is what gives "
            f"mise's own script a truthful $0. Executable lines: {code}"
        )
        assert any('"$@"' in ln for ln in code), f"the {item} wrapper must forward its arguments"
        assert not any("/usr/local/lib/node_modules" in ln for ln in code), (
            "no executable line may reference the path the broken symlink resolved to"
        )
