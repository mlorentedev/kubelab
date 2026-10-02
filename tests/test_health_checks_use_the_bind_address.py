"""A health check must ask the address the port is published on (#959).

A role that binds its published ports to `{{ tailscale_ip }}` leaves nothing
listening on the host's loopback, so a `uri` check against `localhost` is
refused while the service is up. Measured 2026-10-02 on rpi3: Uptime Kuma was
`healthy` and answered 302 over the tailnet, and the provision failed on
`Connection refused` at `http://localhost:3001`. The check had been written
before the bind moved, and rpi3 had not been provisioned since.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROLES = Path(__file__).resolve().parent.parent / "infra/ansible/roles"
PUBLISHED = re.compile(r'^\s*-\s*"([^"]*\{\{[^"]*\}\}[^"]*):[^:"]+:[^:"]+"\s*$', re.MULTILINE)
LOOPBACK = ("localhost", "127.0.0.1", "[::1]")


def _tailnet_only_roles() -> list[Path]:
    """Roles whose every published port is bound to the node's tailnet address."""
    roles = []
    for role in sorted(p for p in ROLES.iterdir() if p.is_dir()):
        binds = [b for t in role.glob("templates/compose*.j2") for b in PUBLISHED.findall(t.read_text())]
        if binds and all("tailscale_ip" in bind for bind in binds):
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
    names = {role.name for role in _tailnet_only_roles()}
    assert {"rpi3_services", "glances", "beelink_services"} <= names, names


@pytest.mark.parametrize("role", _tailnet_only_roles(), ids=lambda r: r.name)
def test_no_health_check_asks_the_loopback(role: Path) -> None:
    for name, url in _uri_urls(role):
        assert not any(host in url for host in LOOPBACK), (
            f"{role.name}: '{name}' asks {url}, but the role publishes its ports on "
            "{{ tailscale_ip }} only, so nothing listens there"
        )
