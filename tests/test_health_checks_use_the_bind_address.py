"""A health check must ask the address the port is published on (#959).

A role that binds its published ports to `{{ tailscale_ip }}` leaves nothing
listening on the host's loopback, so a `uri` check against `localhost` is
refused while the service is up. Measured 2026-10-02 on rpi3: Uptime Kuma was
`healthy` and answered 302 over the tailnet, and the provision failed on
`Connection refused` at `http://localhost:3001`. The check had been written
before the bind moved, and rpi3 had not been provisioned since.

Judged per port, not per role: agent_stack publishes Open WebUI on the tailnet
address and the Hermes API on the loopback, and a loopback check is right for
the second and wrong for the first.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

ROLES = Path(__file__).resolve().parent.parent / "infra/ansible/roles"
LOOPBACK = ("localhost", "127.0.0.1", "[::1]")


def _bindings(template: Path) -> list[tuple[str | None, str]]:
    """(host, host port) of every mapping under a `ports:` key; a None host means all interfaces.

    Every list item in a `ports:` block is read, literal or templated, so a role
    is classified on all of its published ports and not on a matching subset.
    """
    hosts: list[tuple[str | None, str]] = []
    indent = None
    for line in template.read_text().splitlines():
        stripped = line.strip()
        if indent is not None:
            if not stripped or stripped.startswith("#"):
                continue
            if stripped.startswith("- ") and len(line) - len(line.lstrip()) > indent:
                mapping = stripped[2:].split(" #")[0].strip().strip("\"'")
                parts = _split_mapping(mapping)
                hosts.append((parts[0], parts[1]) if len(parts) == 3 else (None, parts[0]))
                continue
            indent = None
        if stripped == "ports:":
            indent = len(line) - len(line.lstrip())
    return hosts


def _split_mapping(mapping: str) -> list[str]:
    """Split `host:port:port` on the colons outside `{{ }}`, which may hold none anyway."""
    parts, depth, current = [], 0, ""
    for i, char in enumerate(mapping):
        depth += mapping.startswith("{{", i) - mapping.startswith("}}", i)
        if char == ":" and depth == 0:
            parts.append(current)
            current = ""
        else:
            current += char
    return [*parts, current]


def _published(role: Path) -> list[tuple[str | None, str]]:
    return [b for t in role.glob("templates/*compose*.yml.j2") for b in _bindings(t)]


def _is_loopback(host: str) -> bool:
    return any(lb in host for lb in LOOPBACK)


def _loopback_free_roles() -> list[Path]:
    """Roles whose every published port names its host: nothing on all interfaces.

    For such a role the loopback answers only on the ports bound to it, whichever
    address the others use: the tailnet one, a LAN one or a public one.
    """
    roles = []
    for role in sorted(p for p in ROLES.iterdir() if p.is_dir()):
        published = _published(role)
        if published and all(host is not None for host, _ in published):
            roles.append(role)
    return roles


def _loopback_port(url: str) -> str | None:
    """The port a URL asks the loopback on, as written (templated or literal)."""
    for host in LOOPBACK:
        marker = f"//{host}:"
        if marker in url:
            return url.split(marker, 1)[1].split("/", 1)[0]
    return None


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
def test_no_health_check_asks_the_loopback_on_a_port_bound_elsewhere(role: Path) -> None:
    on_loopback = {port for host, port in _published(role) if host is not None and _is_loopback(host)}
    for name, url in _uri_urls(role):
        if not any(host in url for host in LOOPBACK):
            continue
        port = _loopback_port(url)
        assert port in on_loopback, (
            f"{role.name}: '{name}' asks {url}, but port {port} is bound to a named "
            "address, so nothing listens for it on the loopback"
        )


def test_a_loopback_check_on_a_tailnet_port_is_still_caught(tmp_path: Path) -> None:
    """The per-port rule must not let a mixed role ask the loopback for its tailnet port."""
    role = tmp_path / "mixed"
    (role / "templates").mkdir(parents=True)
    (role / "tasks").mkdir()
    (role / "templates/compose.yml.j2").write_text(
        "services:\n  a:\n    ports:\n      - \"{{ tailscale_ip }}:3080:8080\"\n"
        "  b:\n    ports:\n      - \"127.0.0.1:{{ api_port }}:{{ api_port }}\"\n"
    )
    (role / "tasks/main.yml").write_text(
        "- name: ok\n  ansible.builtin.uri:\n    url: http://127.0.0.1:{{ api_port }}/health\n"
        "- name: wrong\n  ansible.builtin.uri:\n    url: http://localhost:3080/health\n"
    )
    with pytest.raises(AssertionError, match="'wrong'"):
        test_no_health_check_asks_the_loopback_on_a_port_bound_elsewhere(role)
