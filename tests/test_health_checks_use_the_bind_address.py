"""A health check must ask the address the port is published on (#959).

A role that binds its published ports to `{{ tailscale_ip }}` leaves nothing
listening on the host's loopback, so a `uri` check against `localhost` is
refused while the service is up. Measured 2026-10-02 on rpi3: Uptime Kuma was
`healthy` and answered 302 over the tailnet, and the provision failed on
`Connection refused` at `http://localhost:3001`. The check had been written
before the bind moved, and rpi3 had not been provisioned since.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROLES = Path(__file__).resolve().parent.parent / "infra/ansible/roles"
LOOPBACK = ("localhost", "127.0.0.1", "[::1]")


def _bind_hosts(template: Path) -> list[str | None]:
    """The host part of every mapping under a `ports:` key; None means all interfaces.

    Every list item in a `ports:` block is read, literal or templated, so a role
    is classified on all of its published ports and not on a matching subset.
    """
    hosts: list[str | None] = []
    indent = None
    for line in template.read_text().splitlines():
        stripped = line.strip()
        if indent is not None:
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- ") and len(line) - len(line.lstrip()) > indent:
                mapping = stripped[2:].split(" #")[0].strip().strip("\"'")
                parts = mapping.split(":")
                hosts.append(parts[0] if len(parts) == 3 else None)
                continue
            indent = None
        if stripped == "ports:":
            indent = len(line) - len(line.lstrip())
    return hosts


def _loopback_free_roles() -> list[Path]:
    """Roles whose every published port names a host other than the loopback.

    Nothing listens on the host's loopback for such a role, whichever address
    the ports are bound to: the tailnet one, a LAN one or a public one.
    """
    roles = []
    for role in sorted(p for p in ROLES.iterdir() if p.is_dir()):
        hosts = [h for t in role.glob("templates/*compose*.yml.j2") for h in _bind_hosts(t)]
        if hosts and all(h is not None and not any(lb in h for lb in LOOPBACK) for h in hosts):
            roles.append(role)
    return roles


def _uri_urls(role: Path) -> list[tuple[str, str]]:
    found = []

    def walk(tasks: list) -> None:
        for task in tasks or []:
            if not isinstance(task, dict):
                continue
            for key in ("uri", "ansible.builtin.uri"):
                if key in task:
                    found.append((task.get("name", "<unnamed>"), str(task[key].get("url", ""))))
            for nested in ("block", "rescue", "always"):
                walk(task.get(nested))

    for path in role.glob("tasks/*.yml"):
        walk(yaml.safe_load(path.read_text()))
    return found


def test_the_bound_roles_are_found() -> None:
    names = {role.name for role in _loopback_free_roles()}
    assert {"rpi3_services", "glances", "beelink_services", "agent_stack"} <= names, names
    # A role with one port on all interfaces has something on the loopback.
    assert not {"headscale", "coredns", "traefik_vps"} & names, names


@pytest.mark.parametrize("role", _loopback_free_roles(), ids=lambda r: r.name)
def test_no_health_check_asks_the_loopback(role: Path) -> None:
    for name, url in _uri_urls(role):
        assert not any(host in url for host in LOOPBACK), (
            f"{role.name}: '{name}' asks {url}, but every port the role publishes is "
            "bound to a named address, so nothing listens on the loopback"
        )
