"""No port the DNS stack publishes is bound to an address the node may not have yet (#2732).

A bind that fails takes the container's whole port publication with it, so one
optional port can take DNS down. Two node addresses have done it: the Tailscale
one before tailscaled assigned it (2026-08-22), and the LAN one with the switch
cable out of the edge (2026-10-29, T4 of the hard-reset test). A port is
published bare, which ufw and the edge's forward chain then govern, or bound to
loopback, which exists before Docker starts.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

import yaml
from jinja2 import Environment, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/coredns"


def _compose() -> dict:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
    # Values derived from common.yaml name no port, so a placeholder renders them.
    context = {key: "placeholder" if "{{" in str(value) else value for key, value in defaults.items()}
    source = (ROLE / "templates/docker-compose.yml.j2").read_text()
    template = Environment(undefined=StrictUndefined).from_string(source)
    return yaml.safe_load(template.render(**context))


def _published() -> list[tuple[str, str]]:
    return [(name, str(port)) for name, service in _compose()["services"].items() for port in service.get("ports", [])]


def test_the_guard_reads_every_published_port() -> None:
    ports = _published()
    assert len(ports) >= 6, ports
    assert any(port.count(":") == 2 for _, port in ports), "no bound port left to check"


def _is_loopback(address: str) -> bool:
    try:
        return ipaddress.ip_address(address).is_loopback
    except ValueError:  # derived from common.yaml: a node's address, not a literal
        return False


def test_a_bound_port_is_bound_to_loopback() -> None:
    for service, port in _published():
        parts = port.split(":")
        if len(parts) == 3:
            assert _is_loopback(parts[0]), (
                f"{service} binds {port}: a node address may not exist when Docker starts (#2732)"
            )


def _tasks() -> list[dict]:
    """The role's tasks at any depth: they sit in one block that runs as root."""

    def walk(tasks: list[dict]) -> list[dict]:
        out = []
        for task in tasks:
            out.append(task)
            for key in ("block", "rescue", "always"):
                out.extend(walk(task.get(key) or []))
        return out

    return walk(yaml.safe_load((ROLE / "tasks/main.yml").read_text()))


def test_a_container_left_on_no_network_is_recreated() -> None:
    """A start that failed on a bind leaves the container attached to no network.

    dockerd restores it that way at every boot, and `up -d` sees an unchanged
    spec, so only the shared drift check notices (#2732, #2500).
    """
    tasks = _tasks()
    names = [task.get("name") for task in tasks]
    [check] = [
        i for i, task in enumerate(tasks) if str(task.get("import_tasks", "")).endswith("compose-port-drift.yml")
    ]
    start = names.index("Start DNS stack")
    assert check < start, "the drift check must run before the stack starts"
    # A condition on an import lands on every task it imports.
    assert "when" not in tasks[check]
    [compose] = [
        task["template"]["dest"] for task in tasks if (task.get("template") or {}).get("src") == "docker-compose.yml.j2"
    ]
    assert tasks[check]["vars"]["compose_port_drift_file"] == compose
    command = str(tasks[start]["command"])
    assert "--force-recreate" in command and "compose_port_drift | bool" in command, command
