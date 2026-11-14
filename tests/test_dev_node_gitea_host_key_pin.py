"""ANSIBLE-037 AC3: the dev node pins the forge's SSH host key from the SSOT.

The pin is what makes a first connection from ace2 prompt-free, and safe: the
node refuses a substituted host key instead of adopting it. The live drill
(`specs/.../ac3_host_key_probe.sh`) proves it on powered hardware. This test is
the guard that runs without hardware, so a dropped or weakened pin fails in CI
instead of at the next drill.

Static: it reads the playbook, the role and common.yaml. No cluster, no SOPS.
"""

from __future__ import annotations

import pathlib

import yaml

REPO = pathlib.Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-ace2.yml"
ROLE_TASKS = REPO / "infra/ansible/roles/dev_node/tasks/main.yml"
COMMON = REPO / "infra/config/values/common.yaml"

PIN = "Pin the forge's SSH host key (declared, never scanned)"
SSH_CONFIG = "Point git at the forge with this node's key, without touching dotfiles' files"


def _gitea_block() -> list[dict]:
    for task in yaml.safe_load(ROLE_TASKS.read_text(encoding="utf-8")) or []:
        if isinstance(task, dict) and "gitea" in (task.get("tags") or []) and "block" in task:
            return list(task["block"])
    raise AssertionError("dev_node has no tagged `gitea` block; the tests below would pass vacuously")


def _task(name: str) -> dict:
    for task in _gitea_block():
        if task.get("name") == name:
            return task
    raise AssertionError(f"no task named {name!r} in the gitea block")


def _playbook_vars() -> dict:
    for play in yaml.safe_load(PLAYBOOK.read_text(encoding="utf-8")) or []:
        for role in play.get("roles") or []:
            if isinstance(role, dict) and str(role.get("role", "")).endswith("roles/dev_node"):
                return role.get("vars") or {}
    raise AssertionError("provision-ace2.yml does not apply dev_node with vars")


def test_the_role_pins_the_declared_key_with_known_hosts() -> None:
    pin = _task(PIN)["ansible.builtin.known_hosts"]
    entry = "[{{ dev_node_gitea_ssh_host }}]:{{ dev_node_gitea_ssh_port }}"
    assert pin["name"] == entry, "a non-default port is pinned as [host]:port, or ssh never matches it"
    assert pin["key"] == f"{entry} {{{{ dev_node_gitea_ssh_host_key }}}}"
    assert pin["state"] == "present"


def test_the_key_comes_from_the_ssot_never_a_scan() -> None:
    playbook_vars = _playbook_vars()
    assert playbook_vars["dev_node_gitea_ssh_host_key"] == ("{{ gitea_config.apps.services.core.gitea.ssh_host_key }}")
    gitea = yaml.safe_load(COMMON.read_text(encoding="utf-8"))["apps"]["services"]["core"]["gitea"]
    assert gitea.get("ssh_host_key", "").startswith("ssh-"), "common.yaml declares no forge host key"
    role_text = ROLE_TASKS.read_text(encoding="utf-8")
    assert "ssh-keyscan" not in role_text, "trust-on-first-use is a manual step by another name"


def test_ssh_refuses_an_unknown_forge_key() -> None:
    content = _task(SSH_CONFIG)["ansible.builtin.copy"]["content"]
    assert "StrictHostKeyChecking yes" in content, "without it, a cleared known_hosts would prompt or accept"


def test_only_the_declared_key_type_authenticates_the_forge() -> None:
    """known_hosts keeps entries the role did not write; the declared type is the only one offered."""
    content = _task(SSH_CONFIG)["ansible.builtin.copy"]["content"]
    assert "HostKeyAlgorithms {{ dev_node_gitea_ssh_host_key.split() | first }}" in content
