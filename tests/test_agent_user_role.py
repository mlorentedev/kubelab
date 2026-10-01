"""The agent runs as its own Unix user on a rootless daemon (ADR-068 D2, spec AI-009 PR 2).

ace2 holds staging credentials the dev user may read (ADR-058 D3). The agent must
not: it gets its own user, no sudo, no membership in the `docker` group (that
group is root on the host), and a Docker daemon that runs inside the user's own
namespace. These tests pin the shape of that; the role's own assert tasks prove
it on the node at every provision, because a static test cannot read a home
directory's mode or a daemon's security options.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-ace2.yml"
COMMON = REPO / "infra/config/values/common.yaml"

ROOTFUL_SOCKETS = ("/var/run/docker.sock", "/run/docker.sock")


def _defaults() -> dict:
    return yaml.safe_load((ROLE / "defaults/main.yml").read_text())


def _agent_tasks() -> list[dict]:
    flat: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks/agent_user.yml").read_text()):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _task_with(module: str) -> list[dict]:
    return [task for task in _agent_tasks() if module in task]


def _role_vars() -> dict:
    for role in yaml.safe_load(PLAYBOOK.read_text())[-1]["roles"]:
        if isinstance(role, dict) and role.get("role", "").endswith("agent_stack"):
            return role.get("vars") or {}
    raise AssertionError("agent_stack is not in provision-ace2.yml")


def test_the_main_file_includes_the_agent_user_tasks() -> None:
    main = yaml.safe_load((ROLE / "tasks/main.yml").read_text())
    # Imported, never included: an include's tasks lose the role's tag, so
    # `make provision TAGS=agent_stack` would silently skip them.
    imports = [task for task in main if "ansible.builtin.import_tasks" in task]
    assert any(task["ansible.builtin.import_tasks"] == "agent_user.yml" for task in imports)
    assert not any("include_tasks" in str(key) for task in main for key in task)


def test_the_user_name_comes_from_the_ssot() -> None:
    common = yaml.safe_load(COMMON.read_text())
    assert common["apps"]["services"]["ai"]["hermes_kubelab"]["user"] == "hermes-kubelab"
    assert _role_vars()["agent_stack_agent_user"] == "{{ config.apps.services.ai.hermes_kubelab.user }}"


def test_the_user_holds_no_privilege() -> None:
    (user,) = _task_with("ansible.builtin.user")
    spec = user["ansible.builtin.user"]
    assert spec["name"] == "{{ agent_stack_agent_user }}"
    assert spec.get("system") is True
    # An explicit empty list with append off REMOVES any supplementary group,
    # so a `docker` or `sudo` membership added by hand does not survive a provision.
    assert spec.get("groups") == []
    assert spec.get("append") is False
    assert spec.get("shell") == "/usr/sbin/nologin"


def test_no_task_grants_sudo() -> None:
    for path in ROLE.rglob("*"):
        if path.is_file():
            assert "sudoers" not in path.read_text(), f"{path.relative_to(REPO)} mentions sudoers"


def test_the_daemon_is_the_users_own_socket() -> None:
    host = _defaults()["agent_stack_agent_docker_host"]
    assert host.startswith("unix:///run/user/"), host
    assert host.endswith("/docker.sock"), host


def test_no_template_or_default_can_render_the_rootful_socket() -> None:
    """AC2: the role must not be able to point the agent at the root daemon."""
    for path in [ROLE / "defaults/main.yml", *(ROLE / "templates").glob("*")]:
        text = path.read_text()
        for socket in ROOTFUL_SOCKETS:
            assert socket not in text, f"{path.relative_to(REPO)} names {socket}"


def test_the_installs_run_once() -> None:
    linger = [t for t in _agent_tasks() if "enable-linger" in str(t.get("ansible.builtin.command", ""))]
    assert len(linger) == 1 and "creates" in linger[0]["ansible.builtin.command"]
    setup = [t for t in _agent_tasks() if "dockerd-rootless-setuptool.sh" in str(t.get("ansible.builtin.command", ""))]
    assert len(setup) == 1 and "creates" in setup[0]["ansible.builtin.command"]


def test_the_user_session_tasks_find_the_user_manager() -> None:
    """`systemctl --user` from Ansible needs the user's runtime dir, or it fails on dbus."""
    for task in _agent_tasks():
        if task.get("become_user") == "{{ agent_stack_agent_user }}":
            assert "XDG_RUNTIME_DIR" in (task.get("environment") or {}), task["name"]


def test_the_rootless_packages_are_declared() -> None:
    packages = _defaults()["agent_stack_rootless_packages"]
    for name in ("docker-ce-rootless-extras", "uidmap", "dbus-user-session"):
        assert name in packages


def test_the_protected_paths_cover_the_dev_users_credentials_and_the_root_socket() -> None:
    assert _role_vars()["agent_stack_dev_home"] == "/home/{{ config.networking.ssh_users.homelab }}"
    paths = " ".join(_role_vars()["agent_stack_protected_paths"])
    for fragment in (".config/gh/hosts.yml", ".ssh", ".kube", "/var/run/docker.sock"):
        assert fragment in paths, fragment


def test_each_protected_path_is_asserted_unreadable() -> None:
    reads = [t for t in _agent_tasks() if t.get("loop") == "{{ agent_stack_protected_paths }}"]
    assert len(reads) == 1, "one task must try every protected path as the agent"
    task = reads[0]
    assert task.get("become_user") == "{{ agent_stack_agent_user }}"
    assert task.get("failed_when") == "_agent_stack_protected.rc == 0"


def test_the_daemon_is_proven_rootless_and_able_to_limit_a_container() -> None:
    names = {task.get("name", "") for task in _agent_tasks()}
    assert "Assert the agent's daemon runs rootless" in names
    assert "Run a limited container through the agent's daemon" in names
    assert "Assert the agent's user holds no sudo rule" in names


def test_the_subordinate_ids_are_checked_for_overlap() -> None:
    names = {task.get("name", "") for task in _agent_tasks()}
    assert "Assert no other user's subordinate ids overlap the agent's" in names


def test_the_subordinate_id_parse_splits_on_a_real_newline() -> None:
    """A folded YAML scalar keeps `'\\n'` as two characters, so the parse matched nothing.

    Measured on ace2 2026-10-01: the overlap assert looped over an empty list
    and reported `skipping`. The loaded value must hold an actual newline.
    """
    (task,) = [t for t in _agent_tasks() if t.get("name") == "Parse every user's subordinate ids"]
    expression = task["ansible.builtin.set_fact"]["_agent_stack_subid_lines"]
    assert "join('\n')" in expression and "split('\n')" in expression
