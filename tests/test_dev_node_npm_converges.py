"""Claude Code has one owner on the dev node, and it is not npm (#3566).

The role used to install `@anthropic-ai/claude-code` with the npm module into the
mise node's global tree (#1300 made that converge). The dotfiles' converge also
installs `claude` through mise (`claude = "latest"` in
`~/.config/mise/conf.d/dotfiles.toml`, aqua backend). Two installs of one tool
land in different paths, so which one a shell or an agent launcher runs depends on
PATH order, the two drift to different versions, and nothing reports it. It also
tied the binary to the node that npm ran in: a `NODE_VERSION` bump left
`/usr/local/bin/claude` with nothing behind it until the next provision.

The role now only exposes the mise-managed binary: its `/usr/local/bin/claude`
wrapper asks mise (tests/test_dev_node_mise_owner.py runs it). Nothing here may
install an agent CLI of its own again.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/dev_node"

NPM_MODULES = ("community.general.npm", "npm")
COMMANDS = ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell")


def _tasks() -> list[dict]:
    """Every task in the role, including those nested in a block."""
    flat: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _role_files() -> list[Path]:
    return [p for p in ROLE.rglob("*") if p.is_file()]


def test_no_task_installs_a_package_with_npm() -> None:
    """The npm module with anything but `absent` is an install the dotfiles do not know about."""
    for task in _tasks():
        for key in NPM_MODULES:
            module = task.get(key)
            if module is not None:
                assert module.get("state") == "absent", (
                    f"{task.get('name')!r} installs with npm: a tool the role needs belongs to the dotfiles' mise set"
                )


def test_no_task_runs_npm_install_as_a_raw_command() -> None:
    for task in _tasks():
        for key in COMMANDS:
            body = task.get(key)
            cmd = body.get("cmd", "") if isinstance(body, dict) else (body or "")
            assert "npm install" not in cmd and "npm i " not in cmd, f"{task.get('name')!r} shells out to npm install"


def test_claude_code_is_not_installed_by_the_role() -> None:
    """`absent` is the only way the package may appear: a migration that removes the old install."""
    for task in _tasks():
        if "block" in task:
            continue  # its children are listed on their own
        module = next((task[k] for k in NPM_MODULES if k in task), None)
        if module is not None and "claude-code" in str(module.get("name")):
            assert module.get("state") == "absent"
            continue
        assert "claude-code" not in str(task), f"{task.get('name')!r} still mentions the npm package"


def test_the_defaults_declare_no_agent_npm_packages() -> None:
    for path in _role_files():
        text = path.read_text(encoding="utf-8")
        assert "dev_node_global_agent_npm_packages" not in text, f"{path.relative_to(REPO)} still reads the npm list"
    defaults = (ROLE / "defaults/main.yml").read_text(encoding="utf-8")
    assert "@anthropic-ai/claude-code" not in defaults


# --- the npm install an earlier provision left behind ------------------------
# Dropping the install task does not remove what it installed: the package stays
# in the mise node's lib/node_modules, and its `bin/claude` is a second `claude`
# inside mise until a node bump reinstalls that node. One task retires it.

RETIRE_TASK = "Retire the npm-installed Claude Code the role used to provision"


def _index(name: str) -> int:
    (i,) = [i for i, t in enumerate(_tasks()) if t.get("name") == name]
    return i


def test_the_old_npm_install_is_retired_not_left_as_a_second_claude() -> None:
    task = _tasks()[_index(RETIRE_TASK)]
    module = task["community.general.npm"]
    assert module["name"] == "@anthropic-ai/claude-code"
    assert module["global"] is True
    assert module["state"] == "absent", "present would reinstall the second owner"
    assert module["executable"] == "{{ _dev_node_node_where.stdout | trim }}/bin/npm"
    node_bin = "{{ _dev_node_node_where.stdout | trim }}/bin"
    assert node_bin in task["environment"]["PATH"], "npm is a script that execs node"


def test_the_retirement_runs_after_node_is_resolved_and_repaired_and_carries_their_tags() -> None:
    tasks = _tasks()
    retire = tasks[_index(RETIRE_TASK)]
    resolve = tasks[_index("Resolve the node install mise has active")]
    repair = tasks[_index("Reinstall the active node when its npm or npx is gone")]
    assert tasks.index(resolve) < tasks.index(repair) < tasks.index(retire)
    assert set(retire["tags"]) - {"dev_node"} <= set(resolve["tags"]), "`--tags mise` would read an undefined register"
