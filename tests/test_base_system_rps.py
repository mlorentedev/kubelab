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


def test_the_rule_matches_only_that_interfaces_receive_queues() -> None:
    rule = [line for line in _render("enp1s0", 4).splitlines() if line and not line.startswith("#")]
    assert len(rule) == 1
    assert 'SUBSYSTEM=="queues"' in rule[0]
    assert 'KERNEL=="rx-*"' in rule[0]
    assert 'DEVPATH=="*/net/enp1s0/queues/rx-*"' in rule[0]


def test_the_mask_covers_every_cpu_of_the_node() -> None:
    assert 'ATTR{rps_cpus}="f"' in _render("enp1s0", 4)
    assert 'ATTR{rps_cpus}="ff"' in _render("enp1s0", 8)
