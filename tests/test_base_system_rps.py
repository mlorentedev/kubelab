"""Receive packet steering on a single-queue NIC (#3375).

ace1's r8169 card has one receive queue and one interrupt vector, delivered to one CPU. With RPS off,
every receive softirq runs there, and that CPU is where `web` runs out under load. The role spreads
the receive work across the node's CPUs on the interface a play names, and reads the mask back.
"""

from __future__ import annotations

from pathlib import Path

import jinja2
import yaml

ANSIBLE = Path(__file__).resolve().parent.parent / "infra/ansible"
ROLE = ANSIBLE / "roles/base_system"
DEFAULTS = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))


def _render(interface: str, nproc: int) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    facts = {"ansible_facts": {"processor_nproc": nproc}}
    mask = env.from_string(DEFAULTS["base_system_rps_mask"]).render(**facts)  # Ansible resolves it lazily
    text = (ROLE / "templates/rps.rules.j2").read_text(encoding="utf-8")
    return env.from_string(text).render(
        ansible_managed="managed", base_system_rps_interface=interface, base_system_rps_mask=mask
    )


def _ace1_base_vars() -> dict:
    plays = yaml.safe_load((ANSIBLE / "playbooks/provision-ace1.yml").read_text(encoding="utf-8"))
    for play in plays:
        for role in play.get("roles", []):
            if isinstance(role, dict) and str(role.get("role", "")).endswith("base_system"):
                return role.get("vars", {})
    raise AssertionError("provision-ace1.yml runs no base_system role")


def test_it_is_off_unless_a_play_names_an_interface() -> None:
    assert DEFAULTS["base_system_rps_interface"] == ""


def test_ace1_steers_its_lan_interface_named_once_in_common_yaml() -> None:
    assert _ace1_base_vars()["base_system_rps_interface"] == "{{ config.networking.nodes.ace1.lan_interface }}"


def _rule(interface: str, nproc: int) -> str:
    (rule,) = [line for line in _render(interface, nproc).splitlines() if line and not line.startswith("#")]
    return rule


def test_the_rule_matches_only_that_interface_when_it_appears() -> None:
    """A queue has no uevent file, so a rule on SUBSYSTEM=="queues" is never replayed (seen on ace1)."""
    rule = _rule("enp1s0", 4)
    assert rule.startswith('ACTION=="add", SUBSYSTEM=="net", KERNEL=="enp1s0", ')
    assert "/sys/class/net/%k/queues/rx-*/rps_cpus" in rule


def test_the_mask_covers_every_cpu_of_the_node() -> None:
    assert "echo f > $q" in _rule("enp1s0", 4)
    assert "echo ff > $q" in _rule("enp1s0", 8)


def test_steering_is_on_by_default_once_an_interface_is_named() -> None:
    assert DEFAULTS["base_system_rps_enabled"] is True


def test_the_off_path_removes_the_rule_and_writes_the_kernels_default() -> None:
    """Without it, dropping the change would leave the node steering with no IaC declaring it."""
    tasks = yaml.safe_load((ROLE / "tasks/rps.yml").read_text(encoding="utf-8"))
    (want,) = [t for t in tasks if "ansible.builtin.set_fact" in t]
    assert want["ansible.builtin.set_fact"]["_rps_want"].endswith("else '0' }}")
    (remove,) = [t for t in tasks if "ansible.builtin.file" in t]
    assert remove["ansible.builtin.file"] == {"path": "{{ base_system_rps_rules_path }}", "state": "absent"}
    assert remove["when"] == "not (base_system_rps_enabled | bool)"
