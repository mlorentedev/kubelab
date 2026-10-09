"""Hermes as Open WebUI's second backend (spec AI-009-hermes-ace2 AC4).

Decided 2026-10-08 (verification.md): Open WebUI, on the system daemon, reaches
Hermes, on the agent's rootless daemon, at the host's address in Open WebUI's
own network. A ufw rule admits that network's subnet alone. That works only
because the agent's daemon publishes through rootlesskit's listener in the
host's namespace, whose traffic crosses INPUT; the role proves it at every
provision by having a container on another network refused.
"""

from __future__ import annotations

import ipaddress

import yaml

from tests.test_agent_stack_role import COMMON, ROLE, _context, _environment, _resolved, _tasks

BRIDGE = yaml.safe_load(COMMON.read_text())["networking"]["nodes"]["ace2"]["webui_bridge"]
API_PORT = _context()["agent_stack_hermes"]["api_port"]


def _render(name: str, **overrides: object) -> str:
    env = _environment()
    return env.get_template(name).render(**_resolved(env, **overrides))


def _compose(name: str, **overrides: object) -> dict:
    return yaml.safe_load(_render(name, **overrides))


def _env(**overrides: object) -> dict[str, str]:
    lines = _render("webui.env.j2", **overrides).splitlines()
    return dict(line.split("=", 1) for line in lines if line and not line.startswith("#"))


def _named(name: str) -> dict:
    tasks = [t for t in _tasks() if t.get("name") == name]
    assert len(tasks) == 1, f"{len(tasks)} tasks named {name!r}"
    return tasks[0]


# --------------------------------------------------------------------------- the network


def test_the_bridge_is_private_and_clear_of_every_declared_range() -> None:
    subnet = ipaddress.ip_network(BRIDGE["subnet"])
    common = yaml.safe_load(COMMON.read_text())["networking"]
    assert subnet.is_private
    assert ipaddress.ip_address(BRIDGE["gateway"]) in subnet
    # The system daemon's own bridge, the LAN, and the tailnet the agent is refused:
    # an address in that last one would make the egress rule drop Hermes's replies.
    for taken in ("172.17.0.0/16", common["lan_cidr"], common["tailscale_cidr"]):
        assert not subnet.overlaps(ipaddress.ip_network(taken)), f"{subnet} overlaps {taken}"
    assert len(BRIDGE["name"]) <= 15, "a Linux interface name is at most 15 characters"


def test_open_webuis_network_is_the_declared_bridge() -> None:
    network = _compose("compose-webui.yml.j2")["networks"]["default"]
    assert network["name"] == BRIDGE["network"]
    assert network["driver_opts"]["com.docker.network.bridge.name"] == BRIDGE["name"]
    assert network["ipam"]["config"] == [{"subnet": BRIDGE["subnet"], "gateway": BRIDGE["gateway"]}]


# --------------------------------------------------------------------------- the bind


def test_hermes_is_published_on_the_bridge_gateway_when_open_webui_runs() -> None:
    ports = _compose("compose-hermes.yml.j2")["services"]["hermes"]["ports"]
    assert ports == [f"{BRIDGE['gateway']}:{API_PORT}:{API_PORT}"]


def test_hermes_stays_on_loopback_when_open_webui_does_not_run() -> None:
    """No Open WebUI, no bridge: the address would not exist to bind."""
    ports = _compose("compose-hermes.yml.j2", agent_stack_webui_configured="False")["services"]["hermes"]["ports"]
    assert ports == [f"127.0.0.1:{API_PORT}:{API_PORT}"]


def test_the_provision_reads_the_api_back_where_it_is_published() -> None:
    url = _named("Verify the Hermes API answers with its key")["ansible.builtin.uri"]["url"]
    assert url.startswith("http://{{ _agent_stack_hermes_bind }}:")


# --------------------------------------------------------------------------- the backend


def test_open_webui_lists_nan_then_hermes_with_their_keys_in_the_same_order() -> None:
    env = _env()
    urls = env["OPENAI_API_BASE_URLS"].split(";")
    keys = env["OPENAI_API_KEYS"].split(";")
    assert urls == [_context()["agent_stack_nan_api_base_url"], f"http://{BRIDGE['gateway']}:{API_PORT}/v1"]
    assert keys == ["nan-key-sentinel", "hermes-api-key-sentinel"]


def test_the_hermes_key_exists_before_open_webuis_env_is_rendered() -> None:
    """Open WebUI is deployed first, and its env file carries the key: generated
    after it, the key would render empty on a first provision."""
    main = [t.get("name") for t in yaml.safe_load((ROLE / "tasks/main.yml").read_text())]
    assert main.index("Generate the Hermes API key once") < main.index("Deploy Open WebUI")
    _named("Generate the Hermes API key once")  # one key, generated in one place


# --------------------------------------------------------------------------- the firewall


def test_ufw_admits_the_bridge_subnet_alone_to_the_api() -> None:
    task = _named("Admit Open WebUI's network to the Hermes API")
    rule = task["community.general.ufw"]
    assert rule["rule"] == "allow"
    assert rule["interface_in"] == "{{ agent_stack_webui_bridge.name }}"
    assert rule["from_ip"] == "{{ agent_stack_webui_bridge.subnet }}"
    assert rule["to_ip"] == "{{ agent_stack_webui_bridge.gateway }}"
    assert str(rule["to_port"]) == "{{ agent_stack_hermes.api_port }}"
    assert rule["proto"] == "tcp"


def test_a_container_on_open_webuis_network_reaches_the_api() -> None:
    task = _named("Reach the Hermes API from Open WebUI's network")
    cmd = task["ansible.builtin.command"]["cmd"]
    assert "--network {{ agent_stack_webui_bridge.network }}" in cmd
    assert "{{ agent_stack_webui_bridge.gateway }} {{ agent_stack_hermes.api_port }}" in cmd
    assert "become_user" not in task, "the system daemon's container, not the agent's"


def test_a_container_on_another_network_is_refused_which_is_what_makes_ufw_the_control() -> None:
    task = _named("Try the Hermes API from the system daemon's default network")
    cmd = task["ansible.builtin.command"]["cmd"]
    assert "--network" not in cmd
    assert "{{ agent_stack_webui_bridge.gateway }} {{ agent_stack_hermes.api_port }}" in cmd
    assert task["failed_when"] == "_agent_stack_hermes_other_network.rc == 0"


# --------------------------------------------------------------------------- the boot order


def _unit() -> str:
    return _render("agent-stack-hermes-bind.service.j2")


def test_the_agents_manager_starts_only_once_the_bridge_has_its_address() -> None:
    """The bridge is the system daemon's and Hermes publishes from the agent's user
    manager: at boot the second can start first and find no address to bind."""
    uid = _context()["_agent_stack_agent_uid"]
    unit = _unit()
    assert f"Before=user@{uid}.service" in unit
    assert "After=docker.service" in unit
    assert f"wait-for-tailscale-addr.sh {BRIDGE['gateway']} {BRIDGE['name']}" in unit


def test_a_missing_bridge_delays_the_agent_but_does_not_keep_it_down() -> None:
    """Availability, not containment: without the address the bind fails closed,
    so the egress rule's RequiredBy= would only cost the agent its other work."""
    uid = _context()["_agent_stack_agent_uid"]
    unit = _unit()
    assert f"WantedBy=user@{uid}.service" in unit
    assert "RequiredBy=" not in unit


def test_the_boot_unit_exists_exactly_while_hermes_publishes_on_the_bridge() -> None:
    gate = "agent_stack_hermes_configured | bool and agent_stack_webui_configured | bool"
    assert _named("Install the unit that waits for Open WebUI's bridge")["when"] == gate
    assert _named("Remove the unit that waits for Open WebUI's bridge")["when"] == f"not ({gate})"


def test_a_hermes_container_left_unbound_is_recreated() -> None:
    """A port binding is fixed at create time: a gateway created before the address
    existed runs with no port, and an unchanged spec hash keeps `up -d` off it."""
    probe = _named("Read the Hermes port bindings requested vs the ones in effect")
    assert "hermes-kubelab" in probe["ansible.builtin.command"]
    start = _named("Start hermes-kubelab")["ansible.builtin.command"]
    assert "_agent_stack_hermes_unbound" in start
