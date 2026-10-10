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
PRIVATE = ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10", "172.80.0.0/12"]


def _render(path: Path, **extra: object) -> str:
    env = jinja2.Environment(undefined=jinja2.StrictUndefined, keep_trailing_newline=True)
    context = {
        "_agent_stack_agent_uid": UID,
        "agent_stack_tailnet_ranges": RANGES,
        "agent_stack_private_ranges": PRIVATE,
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
    assert all(r.startswith(f"meta skuid {UID} ") and r.endswith("reject with icmpx type admin-prohibited") for r in rules)
    assert any(f"ct original ip daddr {RANGES[0]}" in r for r in rules), rules
    assert any(f"ct original ip6 daddr {RANGES[1]}" in r for r in rules), rules
    # The tailnet is in both lists; one rule each.
    assert len(rules) == len(set(rules)), rules


def test_every_private_range_is_refused_to_the_agents_uid() -> None:
    """The homelab LAN, docker0, Open WebUI's network and the system daemon's
    address pool are this node's, not the agent's (#2161). Measured on ace2
    2026-10-10 before this rule: the agent's user opened rpi4:80, Beelink's and
    ace2's own sshd, and Open WebUI's backend by its container address."""
    rules = _rules(_render(TABLE))
    for cidr in PRIVATE:
        assert any(f"ct original ip daddr {cidr}" in r and "reject" in r for r in rules), cidr


def test_the_agent_may_still_answer_a_connection_it_did_not_open() -> None:
    """Hermes publishes on Open WebUI's bridge gateway through rootlesskit, a
    process of the agent's user (lesson-542). A reply to Open WebUI's request has
    that gateway, a private address, as its original destination: a rule on the
    destination alone would drop every answer. Only new connections are refused."""
    for rule in _rules(_render(TABLE)):
        assert "ct state new" in rule, rule


def test_the_private_ranges_come_from_the_ssot() -> None:
    assert _role_vars()["agent_stack_private_ranges"] == (
        "{{ config.networking.trusted_cidrs + [docker_address_pool_base] }}"
    )
    net = yaml.safe_load(COMMON.read_text())["networking"]
    pool = yaml.safe_load((REPO / "infra/ansible/roles/docker/defaults/main.yml").read_text())
    assert net["trusted_cidrs"] + [pool["docker_address_pool_base"]] == PRIVATE
    # Every RFC 1918 block, so the LAN, docker0 and every user bridge are in.
    for block in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"):
        assert block in net["trusted_cidrs"]


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
    # The one line that could flush the node: it loads this table's file and
    # nothing else, and stopping deletes this table and nothing else.
    lines = {k: v for k, _, v in (line.partition("=") for line in unit.splitlines() if "=" in line)}
    load = "/usr/sbin/nft -f {{ agent_stack_dir }}/agent-egress.nft"
    assert lines["ExecStart"] == load and lines["ExecReload"] == load
    assert lines["ExecStop"] == "/usr/sbin/nft delete table inet agent_egress"


def test_the_rule_is_loaded_before_the_agents_user_manager_is_started() -> None:
    tasks = _agent_tasks()
    names = [t.get("name", "") for t in tasks]
    (load,) = [
        i
        for i, t in enumerate(tasks)
        if t.get("ansible.builtin.systemd", {}).get("name") == "agent-stack-egress.service"
        and t["ansible.builtin.systemd"].get("state") == "started"
    ]
    # `enabled` is what writes the RequiredBy link: without it the agent's
    # manager starts at boot with no rule, which is the hole this closes.
    assert tasks[load]["ansible.builtin.systemd"].get("enabled") is True
    assert load < names.index("Start the agent's user manager")


def _assert_controlled(tasks: list[dict], probe: dict) -> None:
    """A refusal measures something only if the same address and port answered just
    before, from outside the rule (as root): nc fails the same on a dead path."""
    target = re.search(r"nc -z -w \d+ (\{\{ \w+ \}\}) (\{\{ [\w.]+ \}\})", probe["ansible.builtin.command"]["cmd"])
    assert target, "every probe names its host and port as role variables"
    host, port = target.groups()
    controls = [
        i
        for i, t in enumerate(tasks)
        if t.get("ansible.builtin.wait_for", {}).get("host") == host
        and t["ansible.builtin.wait_for"].get("port") == port
    ]
    assert controls and controls[0] < tasks.index(probe), f"no control proves {host}:{port} open before the probe"
    assert "become_user" not in tasks[controls[0]], "the control must run outside the agent's uid"


def test_every_provision_proves_the_tailnet_refused_and_the_internet_open() -> None:
    tasks = _agent_tasks()
    probes = [t for t in tasks if "nc -z" in str(t.get("ansible.builtin.command", ""))]
    assert len(probes) == 5, (
        "the VPS's tailnet address, this node's own published port, its LAN address, "
        "Open WebUI's container address, the internet control"
    )
    own_port = "{{ tailscale_ip }} {{ agent_stack_webui.default_port }}"
    local = [p for p in probes if own_port in p["ansible.builtin.command"]["cmd"]]
    assert len(local) == 1 and "rc == 0" in local[0]["failed_when"], "the DNAT case must be refused"
    remote = [p for p in probes if "agent_stack_egress_probe_refused" in p["ansible.builtin.command"]["cmd"]]
    assert len(remote) == 1
    _assert_controlled(tasks, remote[0])
    # nc fails the same on a closed port: the port must be proven open first,
    # from outside the rule, or a refusal measures nothing.
    _assert_controlled(tasks, local[0])
    for probe in probes:
        assert probe.get("check_mode") is False and probe.get("changed_when") is False
        assert probe.get("become_user") == "{{ agent_stack_agent_user }}"
        assert "--network none" not in probe["ansible.builtin.command"]["cmd"]
    lan = [p for p in probes if "agent_stack_egress_probe_lan" in p["ansible.builtin.command"]["cmd"]]
    container = [p for p in probes if "_agent_stack_webui_address" in p["ansible.builtin.command"]["cmd"]]
    assert len(lan) == 1 and len(container) == 1
    for probe in (lan[0], container[0]):
        assert "rc == 0" in probe["failed_when"]
        _assert_controlled(tasks, probe)
    role_vars = _role_vars()
    assert role_vars["agent_stack_egress_probe_lan"] == "{{ config.networking.nodes.ace2.lan_ip }}"
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
