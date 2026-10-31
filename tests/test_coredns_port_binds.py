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

import pytest
import yaml
from jinja2 import Environment, StrictUndefined

REPO = Path(__file__).resolve().parent.parent
ROLE = REPO / "infra/ansible/roles/coredns"


def _compose() -> dict:
    defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text(encoding="utf-8"))
    # Values derived from common.yaml name no port, so a placeholder renders them.
    context = {key: "placeholder" if "{{" in str(value) else value for key, value in defaults.items()}
    source = (ROLE / "templates/docker-compose.yml.j2").read_text(encoding="utf-8")
    template = Environment(undefined=StrictUndefined).from_string(source)
    return yaml.safe_load(template.render(**context))


def _published() -> list[tuple[str, str | dict]]:
    return [(name, port) for name, service in _compose()["services"].items() for port in service.get("ports", [])]


def _host_ip(port: str | dict) -> str | None:
    """The address a port is bound to, in the short form or the long one; None if bare."""
    if isinstance(port, dict):
        return port.get("host_ip")
    if port.startswith("["):  # [::1]:8080:8080
        return port[1 : port.index("]")]
    parts = port.split(":")
    return parts[0] if len(parts) == 3 else None


def test_the_guard_reads_every_published_port() -> None:
    ports = _published()
    assert len(ports) >= 6, ports
    assert any(_host_ip(port) for _, port in ports), "no bound port left to check"


def _binds_safely(address: str) -> bool:
    """Loopback exists before Docker starts, and 0.0.0.0 or :: is a bare publish."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:  # derived from common.yaml: a node's address, not a literal
        return False
    return ip.is_loopback or ip.is_unspecified


@pytest.mark.parametrize(
    ("port", "safe"),
    [
        ("127.0.0.1:8080:8080/tcp", True),
        ("[::1]:8080:8080", True),
        ("0.0.0.0:53:53/udp", True),
        ({"target": 8080, "published": 8080, "host_ip": "127.0.0.1"}, True),
        ("{{ lan_ip }}:8080:8080/tcp", False),
        ("[2001:db8::1]:8080:8080", False),
        ({"target": 8080, "published": 8080, "host_ip": "192.0.2.1"}, False),
    ],
)
def test_the_guard_reads_each_form_of_a_bound_port(port: str | dict, safe: bool) -> None:
    assert _binds_safely(_host_ip(port) or "0.0.0.0") is safe


def test_a_bound_port_is_bound_to_loopback() -> None:
    for service, port in _published():
        address = _host_ip(port)
        if address is not None:
            assert _binds_safely(address), (
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

    return walk(yaml.safe_load((ROLE / "tasks/main.yml").read_text(encoding="utf-8")))


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
