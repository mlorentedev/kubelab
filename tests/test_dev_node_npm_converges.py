"""The dev node's global agent CLIs are installed once, not on every provision (#1300).

The role used to run `mise exec -- npm install -g <pkg>` with
`changed_when: "'added' in stdout or 'changed' in stdout"`. npm prints
`changed 2 packages` for a package that is already installed at the same
version, because it rewrites the shims and calls that a change. So the guard
matched the case it was written to exclude, the task reported `changed` on every
pass, and every provision reinstalled Claude Code.

The fix declares the state instead of parsing npm's prose: the `npm` module with
`state: present` lists the global tree first and installs only what is missing.

Not pinned, deliberately. `@anthropic-ai/claude-code` updates itself in place
(measured on ace2 2026-10-01: npm-installed, 2.1.241). A pinned version would
make Ansible and the updater take turns: the updater moves it forward, the next
provision moves it back and reports `changed`. That is the same unconverging role
under a different cause. `present` leaves the version to the updater and the
existence of the tool to Ansible.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/dev_node"


def _tasks() -> list[dict]:
    """Every task in the role, including those nested in a block."""
    flat: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks/main.yml").read_text()):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _npm_install_task() -> dict:
    for task in _tasks():
        if task.get("loop") == "{{ dev_node_global_agent_npm_packages }}":
            return task
    raise AssertionError("no task loops over dev_node_global_agent_npm_packages")


def test_global_agent_clis_use_the_npm_module_not_a_command() -> None:
    task = _npm_install_task()
    module = task.get("community.general.npm")
    assert module is not None, (
        "the global agent CLI install must use community.general.npm; a command "
        "task depends on parsing npm's output, which says `changed` for a no-op"
    )
    assert module.get("global") is True
    assert module.get("name") == "{{ item }}"


def test_the_install_ensures_presence_and_never_chases_latest() -> None:
    module = _npm_install_task()["community.general.npm"]
    assert module.get("state", "present") == "present", (
        "state must be present: `latest` reinstalls whenever the registry moves, "
        "and the CLI already updates itself"
    )


def test_the_install_uses_the_pinned_mise_node() -> None:
    """The module must run the node the role pins, not whatever is first on PATH."""
    task = _npm_install_task()

    def resolve(value: str) -> str:
        for name, sub in (task.get("vars") or {}).items():
            value = value.replace("{{ " + name + " }}", sub)
        return value

    executable = resolve(task["community.general.npm"].get("executable", ""))
    assert "mise/installs/node/{{ dev_node_toolchains.node }}/bin/npm" in executable
    assert "mise/installs/node/{{ dev_node_toolchains.node }}/bin" in resolve(task["environment"]["PATH"]), (
        "mise's bin/npm is a script that execs `node`, so node must be on PATH too"
    )


def test_no_task_runs_npm_install_as_a_raw_command() -> None:
    for task in _tasks():
        for key in ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell"):
            body = task.get(key)
            cmd = body.get("cmd", "") if isinstance(body, dict) else (body or "")
            assert "npm install -g" not in cmd, f"{task.get('name')!r} still shells out to npm install -g"


def _task_named(name: str) -> dict:
    for task in _tasks():
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r}")


def test_the_forge_key_is_looked_up_by_fingerprint() -> None:
    """The forge answers whether the key is registered; the role does not parse a list.

    The previous comparison ran `regex_replace(..., '\\2')` inside Jinja, which
    reads '\\2' as chr(2). No key ever matched, so every pass after the first
    POSTed the key again and failed on Gitea's 422 (ace2, 2026-10-01).
    """
    lookup = _task_named("Look up this node's key on the machine account")
    assert "/users/{{ dev_node_gitea_user }}/keys?fingerprint=" in lookup["ansible.builtin.uri"]["url"], (
        "a fingerprint query on /user/keys is not restricted to an owner, so another account's copy would match"
    )
    register = _task_named("Register this node's public key on the machine account")
    when = " ".join(register["when"]) if isinstance(register["when"], list) else register["when"]
    assert "regex_replace" not in when
    assert "_gitea_keys.json" in when
    assert "selectattr('fingerprint'" in when, (
        "match the fingerprint on the answer too: a forge that ignored the filter "
        "would return every key, and any key would read as this node's"
    )
    assert register["changed_when"] == "_gitea_key_post.status == 201", "a POST that creates a key is a change"


def test_the_forge_key_lookup_survives_a_dry_run() -> None:
    """`--check` skips a `command` task, and the lookup templates its stdout."""
    lookup = _task_named("Look up this node's key on the machine account")
    assert lookup.get("check_mode") is False
    assert lookup.get("when") == "_gitea_key_fp.rc == 0"
