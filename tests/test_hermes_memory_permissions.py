"""Ownership and lock-safety contract for Hermes's shared vault mounts (#3485)."""

from __future__ import annotations

from pathlib import Path

import yaml

from tests.test_agent_stack_role import _environment, _resolved
from tests.test_hermes_config import _config, _render

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
VAULT_TASKS = yaml.safe_load((ROLE / "tasks/vault_zone.yml").read_text(encoding="utf-8"))
HERMES_TASKS = yaml.safe_load((ROLE / "tasks/hermes.yml").read_text(encoding="utf-8"))


def _flat(tasks: list[dict]) -> list[dict]:
    return [nested for task in tasks for nested in [task, *task.get("block", [])]]


def _named(tasks: list[dict], fragment: str) -> dict:
    matches = [task for task in _flat(tasks) if fragment in task.get("name", "")]
    assert len(matches) == 1, (fragment, [task.get("name") for task in _flat(tasks)])
    return matches[0]


def test_sandboxes_use_the_gateway_uid_through_the_pinned_config_key() -> None:
    terminal = _config()["terminal"]
    assert terminal["docker_run_as_host_user"] is True
    assert "docker_user" not in terminal


def test_host_ownership_is_derived_from_the_rootless_subordinate_ranges() -> None:
    resolved = _resolved(_environment())
    assert resolved["_agent_stack_hermes_uid"] == 10000
    assert resolved["_agent_stack_hermes_gid"] == 10000
    assert int(resolved["_agent_stack_hermes_host_uid"]) == int(resolved["agent_stack_agent_subid_start"]) + 9999
    assert int(resolved["_agent_stack_hermes_host_gid"]) == int(resolved["agent_stack_agent_subid_start"]) + 9999


def test_the_vault_root_allows_traverse_without_allowing_a_listing() -> None:
    task = _named(VAULT_TASKS, "Create the vault clone's directory")
    assert task["ansible.builtin.file"]["mode"] == "0711"


def test_the_zone_and_memories_have_one_effective_owner_and_no_sticky_bit() -> None:
    zone = _named(VAULT_TASKS, "Create the vault zone itself")
    memories = _named(VAULT_TASKS, "Create the memories directory")
    for task in (zone, memories):
        spec = task["ansible.builtin.file"]
        assert spec["state"] == "directory"
        assert spec["owner"] == "{{ _agent_stack_hermes_host_uid }}"
        assert spec["group"] == "{{ _agent_stack_hermes_host_gid }}"
        assert spec["mode"] == "0755"


def test_existing_zone_files_are_reclaimed_without_touching_curator_inputs() -> None:
    task = _named(VAULT_TASKS, "Reclaim existing vault-zone ownership")
    spec = task["ansible.builtin.file"]
    assert spec["path"] == "{{ item.path }}"
    assert spec["owner"] == "{{ _agent_stack_hermes_host_uid }}"
    assert spec["group"] == "{{ _agent_stack_hermes_host_gid }}"
    assert "mode" not in spec, "memory files stay 0600; the namespace-aware sync reads them"
    assert any("curator" in condition for condition in task["when"])


def test_deleted_locks_are_not_reclaimed_after_they_are_removed() -> None:
    task = _named(VAULT_TASKS, "Reclaim existing vault-zone ownership")
    assert any(
        "item.path not in" in condition and "_agent_stack_vault_memory_locks" in condition
        for condition in task["when"]
    ), "the pre-cleanup inventory includes locks that no longer exist by this task"


def test_stale_locks_are_removed_only_after_writers_stop() -> None:
    names = [task.get("name", "") for task in _flat(VAULT_TASKS)]
    stop = names.index("Stop the gateway before repairing shared vault files")
    sandboxes = names.index("Stop sandboxes before repairing shared vault files")
    cleanup = names.index("Remove stale memory lock files")
    reclaim = names.index("Reclaim existing vault-zone ownership")
    assert stop < sandboxes < cleanup < reclaim
    for fragment in (
        "Stop the gateway before repairing shared vault files",
        "Stop sandboxes before repairing shared vault files",
        "Remove stale memory lock files",
    ):
        task = _named(VAULT_TASKS, fragment)
        assert any("_agent_stack_vault_repair_needed" in condition for condition in task["when"])


def test_locks_and_atomic_temporaries_stay_out_of_git() -> None:
    task = _named(VAULT_TASKS, "Install the vault sync's ignore file")
    content = task["ansible.builtin.copy"]["content"]
    assert "{{ agent_stack_vault_zone }}/memories/*.lock" in content
    assert "{{ agent_stack_vault_zone }}/memories/.mem_*" in content


def test_namespace_aware_sync_is_preserved_for_0600_memory_files() -> None:
    script = (ROLE / "templates/vault-sync.sh.j2").read_text(encoding="utf-8")
    assert "VAULT_SYNC_IN_USERNS=1 exec nsenter --user" in script
    assert "dockerd-rootless" in script


def test_cache_document_delegation_and_workspace_paths_are_deterministically_writable() -> None:
    task = _named(HERMES_TASKS, "Create Hermes writable runtime directories")
    spec = task["ansible.builtin.file"]
    assert spec["owner"] == "{{ _agent_stack_hermes_host_uid }}"
    assert spec["group"] == "{{ _agent_stack_hermes_host_gid }}"
    assert spec["mode"] == "0755"
    assert set(task["loop"]) == {
        "{{ agent_stack_hermes_home }}/cache",
        "{{ agent_stack_hermes_home }}/cache/delegation",
        "{{ agent_stack_hermes_home }}/cache/documents",
        "{{ agent_stack_hermes_home }}/workspace",
    }


def test_managed_skills_stay_read_only() -> None:
    gateway = yaml.safe_load(_render("compose-hermes.yml.j2", agent_stack_vault_configured=True))["services"]["hermes"]
    home = gateway["environment"]["HERMES_HOME"]
    assert any(v.endswith(f"{home}/memories") and not v.endswith(":ro") for v in gateway["volumes"])
    assert any(v.endswith("/hermes-skills:ro") for v in gateway["volumes"])


def test_repairs_are_conditional_so_a_clean_second_run_changes_nothing() -> None:
    stop = _named(VAULT_TASKS, "Stop the gateway before repairing shared vault files")
    assert "not ansible_check_mode" in stop["when"]
    assert any("_agent_stack_vault_repair_needed" in condition for condition in stop["when"])
    assert stop["changed_when"] is True
