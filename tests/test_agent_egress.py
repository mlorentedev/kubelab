"""The agent's user never reaches the tailnet as ace2 (spec AI-009 AC5, lesson-525).

On a tailnet node, a container's egress is the host's routing table, so a
container of the agent's rootless daemon reached the VPS's `:22` and `:6443`,
both K3s APIs, Gitea and Open WebUI carrying ace2's identity (2026-10-06).
Every packet that daemon emits leaves the host from a process the agent's user
owns (slirp4netns), so one host rule on that uid closes the path for the
gateway, the sidecar and every sandbox, whatever their own network settings.

The rule lives in its own nftables table, loaded by its own unit. Never
`nftables.service`: its `/etc/nftables.conf` starts with `flush ruleset`, which
would erase Docker's, ufw's and Tailscale's rules on the node.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import jinja2
import yaml

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/agent_stack"
PLAYBOOK = REPO / "infra/ansible/playbooks/provision-ace2.yml"
COMMON = REPO / "infra/config/values/common.yaml"
TABLE = ROLE / "templates/agent-egress.nft.j2"
UNIT = ROLE / "templates/agent-stack-egress.service.j2"

UID = "998"
RANGES = ["100.64.0.0/10", "fd7a:115c:a1e0::/48"]


def _render(path: Path, **extra: object) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    context = {
        "_agent_stack_agent_uid": UID,
        "agent_stack_tailnet_ranges": RANGES,
        "agent_stack_egress_table": "{{ agent_stack_dir }}/agent-egress.nft",
        **extra,
    }
    return env.from_string(path.read_text()).render(**context)


def _agent_tasks() -> list[dict]:
    flat: list[dict] = []
    for task in yaml.safe_load((ROLE / "tasks/agent_user.yml").read_text()):
        flat.append(task)
        flat.extend(task.get("block") or [])
    return flat


def _role_vars() -> dict:
    for role in yaml.safe_load(PLAYBOOK.read_text())[-1]["roles"]:
        if isinstance(role, dict) and role.get("role", "").endswith("agent_stack"):
            return role.get("vars") or {}
    raise AssertionError("agent_stack is not in provision-ace2.yml")


def _rules(table: str) -> list[str]:
    return [line.strip() for line in table.splitlines() if "meta skuid" in line]


def test_both_tailnet_ranges_are_refused_to_the_agents_uid() -> None:
    rules = _rules(_render(TABLE))
    assert any(f"meta skuid {UID} ct original ip daddr {RANGES[0]}" in r and "reject" in r for r in rules), rules
    assert any(f"meta skuid {UID} ct original ip6 daddr {RANGES[1]}" in r and "reject" in r for r in rules), rules


def test_the_rule_judges_the_destination_before_nat() -> None:
    """A port another daemon publishes on this node's tailnet address is DNATed in
    nat OUTPUT (priority -100), before a filter chain at priority 0 runs, so a plain
    `daddr` sees the container's address and lets it through. Measured on ace2
    2026-10-07: Open WebUI at ace2:3080 answered the agent's gateway under a
    `daddr` rule. conntrack's original tuple is the address the agent asked for."""
    for rule in _rules(_render(TABLE)):
        assert "ct original" in rule, rule


def test_the_rule_matches_the_uid_number_not_the_name() -> None:
    # A name is resolved through NSS when the table loads; the number needs nothing.
    assert '"' not in "".join(_rules(_render(TABLE)))


def test_the_table_replaces_itself_and_nothing_else() -> None:
    table = _render(TABLE)
    assert "flush ruleset" not in table
    # Declare-then-delete makes a reload idempotent: the delete never fails on a
    # missing table, and nothing outside this table is touched.
    assert re.search(r"^table inet agent_egress\s*$", table, re.M)
    assert re.search(r"^delete table inet agent_egress\s*$", table, re.M)


def test_the_ranges_come_from_the_networking_ssot() -> None:
    net = yaml.safe_load(COMMON.read_text())["networking"]
    assert (net["tailscale_cidr"], net["ipv6_prefix"]) == tuple(RANGES)
    assert _role_vars()["agent_stack_tailnet_ranges"] == [
        "{{ config.networking.tailscale_cidr }}",
        "{{ config.networking.ipv6_prefix }}",
    ]
    src = re.sub(r"#[^\n]*", "", TABLE.read_text())
    assert not re.search(r"\d{1,3}(\.\d{1,3}){3}|fd7a", src), "the template must not hardcode a range"


def test_the_unit_is_its_own_and_comes_before_the_agents_user_manager() -> None:
    unit = _render(UNIT)
    assert "nftables.service" not in re.sub(r"#[^\n]*", "", unit)
    assert f"Before=user@{UID}.service" in unit
    # Fail closed: without the rule the agent's manager, and so its daemon, does
    # not start, and stopping the rule stops them.
    assert f"RequiredBy=user@{UID}.service" in unit
    assert "RemainAfterExit=yes" in unit


def test_the_rule_is_loaded_before_the_agents_user_manager_is_started() -> None:
    names = [t.get("name", "") for t in _agent_tasks()]
    load = next(i for i, t in enumerate(_agent_tasks()) if "agent-stack-egress" in str(t.get("ansible.builtin.systemd", "")))
    start = names.index("Start the agent's user manager")
    assert load < start


def test_every_provision_proves_the_tailnet_refused_and_the_internet_open() -> None:
    tasks = _agent_tasks()
    probes = [t for t in tasks if "nc -z" in str(t.get("ansible.builtin.command", ""))]
    assert len(probes) == 3, "the VPS's tailnet address, this node's own published port, the internet control"
    local = [p for p in probes if "{{ tailscale_ip }} {{ agent_stack_webui.default_port }}" in p["ansible.builtin.command"]["cmd"]]
    assert len(local) == 1 and "rc == 0" in local[0]["failed_when"], "the DNAT case must be refused"
    # nc fails the same on a closed port: the port must be proven open first,
    # from outside the rule, or a refusal measures nothing.
    control = [i for i, t in enumerate(tasks) if t.get("ansible.builtin.wait_for", {}).get("port") == "{{ agent_stack_webui.default_port }}"]
    assert control and control[0] < tasks.index(local[0]), "no control proves the port open before the probe"
    assert "become_user" not in tasks[control[0]], "the control must run outside the agent's uid"
    for probe in probes:
        assert probe.get("check_mode") is False and probe.get("changed_when") is False
        assert probe.get("become_user") == "{{ agent_stack_agent_user }}"
        assert "--network none" not in probe["ansible.builtin.command"]["cmd"]
    role_vars = _role_vars()
    assert role_vars["agent_stack_egress_probe_refused"] == "{{ config.networking.vps.tailscale_ip }}"
    assert role_vars["agent_stack_egress_probe_open"] == "{{ config.networking.vps.public_ip }}"


def test_the_agents_containers_resolve_outside_the_refused_ranges() -> None:
    """MagicDNS is 100.100.100.100, inside 100.64.0.0/10: listed, it is a resolver
    every query fails on before falling through, so it must not be listed."""
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    servers = defaults["agent_stack_hermes_dns_servers"]
    assert servers
    for server in servers:
        address = ipaddress.ip_address(server)
        assert not any(address in ipaddress.ip_network(r) for r in RANGES), server
    compose = (ROLE / "templates/compose-hermes.yml.j2").read_text()
    assert "agent_stack_hermes_dns_servers" in compose
    assert "agent_stack_docker_dns_servers" not in compose
