"""`base_system` owns a LAN node's whole netplan, and applies it behind a revert.

netplan merges `nameservers.addresses` across files, so the installer's file on bee
added public servers to the role's, and resolved held `8.8.8.8 1.1.1.1 172.16.1.1`.
Those answer prod names differently (lesson-682, #2909).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
import yaml

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/base_system"
SCRIPT = ROLE / "files/netplan-revert.sh"
NETWORKING = yaml.safe_load((REPO / "infra/config/values/common.yaml").read_text(encoding="utf-8"))["networking"]
GATEWAY = NETWORKING["nodes"]["rpi4"]["lan_ip"]
TASKS = yaml.safe_load((ROLE / "tasks/netplan.yml").read_text(encoding="utf-8"))
(APPLY,) = [t for t in TASKS if "block" in t]
BLOCK = [t["name"] for t in APPLY["block"]]


def _rendered() -> dict:
    env = ansible_env(str(ROLE / "templates"), trim_blocks=True)
    text = env.get_template("netplan.yaml.j2").render(
        ansible_managed="managed",
        netplan_interface="enp1s0",
        netplan_address=f"{NETWORKING['nodes']['beelink']['lan_ip']}/24",
        netplan_gateway=GATEWAY,
    )
    return yaml.safe_load(text)["network"]["ethernets"]["enp1s0"]


def test_the_only_resolver_and_gateway_are_the_declared_edge() -> None:
    link = _rendered()
    assert link["nameservers"]["addresses"] == [GATEWAY]
    assert link["routes"] == [{"to": "default", "via": GATEWAY}]


@pytest.mark.parametrize("playbook", ["provision-ace1", "provision-ace2", "provision-bee"])
def test_every_lan_node_takes_its_gateway_from_the_ssot(playbook: str) -> None:
    text = (REPO / f"infra/ansible/playbooks/{playbook}.yml").read_text(encoding="utf-8")
    assert 'netplan_gateway: "{{ config.networking.nodes.rpi4.lan_ip }}"' in text


def test_a_file_the_role_does_not_own_is_removed() -> None:
    (removal,) = [t for t in APPLY["block"] if t.get("file", {}).get("state") == "absent"]
    assert removal["loop"] == "{{ _netplan_foreign }}"


def test_the_apply_condition_reads_the_live_link_and_not_only_the_file() -> None:
    """A file already on disk says nothing about an apply that never ran (lesson-620)."""
    condition = " ".join(APPLY["when"])
    assert "_netplan_live_servers" in condition
    assert "_netplan_foreign" in condition


def test_the_revert_is_armed_before_anything_is_written_and_disarmed_last() -> None:
    order = [
        BLOCK.index(name)
        for name in (
            "Back up the current netplan",
            "Arm the revert, in case the node stops answering",
            "Write the declared netplan",
            "Remove the netplan files the role does not own",
            "Check the netplan before applying it",
            "Apply the netplan",
            "Wait for the node after the apply",
            "Prove a name resolves over the new resolvers",
            "Disarm the revert",
        )
    ]
    assert order == sorted(order)
    assert BLOCK[-1] == "Disarm the revert"


def test_no_netplan_task_notifies_a_handler() -> None:
    assert "notify" not in (ROLE / "tasks/netplan.yml").read_text(encoding="utf-8")


def _fake_tools(root: Path) -> dict[str, str]:
    bin_dir = root / "bin"
    bin_dir.mkdir()
    for tool in ("netplan", "systemctl"):
        path = bin_dir / tool
        path.write_text(f'#!/bin/sh\necho "{tool} $*" >>"{root}/calls"\n', encoding="utf-8")
        path.chmod(0o755)
    return {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "NETPLAN_DIR": str(root / "netplan"),
        "NETPLAN_BACKUP": str(root / "backup"),
    }


def test_restore_puts_back_exactly_what_the_backup_held(tmp_path: Path) -> None:
    env = _fake_tools(tmp_path)
    netplan = tmp_path / "netplan"
    netplan.mkdir()
    (netplan / "00-installer-config.yaml").write_text("old", encoding="utf-8")
    subprocess.run([SCRIPT, "backup"], env=env, check=True)
    (netplan / "00-installer-config.yaml").unlink()
    (netplan / "50-cloud-init.yaml").write_text("new", encoding="utf-8")

    subprocess.run([SCRIPT, "restore"], env=env, check=True)

    assert [p.name for p in netplan.iterdir()] == ["00-installer-config.yaml"]
    assert "netplan apply" in (tmp_path / "calls").read_text(encoding="utf-8")


def test_restore_without_a_backup_leaves_the_netplan_alone(tmp_path: Path) -> None:
    env = _fake_tools(tmp_path)
    netplan = tmp_path / "netplan"
    netplan.mkdir()
    (netplan / "50-cloud-init.yaml").write_text("new", encoding="utf-8")
    (tmp_path / "backup").mkdir()

    assert subprocess.run([SCRIPT, "restore"], env=env, check=False, capture_output=True).returncode != 0
    assert (netplan / "50-cloud-init.yaml").exists()
