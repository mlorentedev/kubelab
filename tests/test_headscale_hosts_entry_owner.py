"""One role owns the Headscale line in /etc/hosts (ANSIBLE-063, #2039).

`vpn.kubelab.live` must resolve to the VPS public IP from /etc/hosts, so a node
can reach Headscale before the mesh or DNS is up. `dns_resilience` writes that
line on every node. `gateway` used to write it too on rpi4, through its own
variables: one fact with two owners, two variable paths, and a real apply that
wrote the line twice. This fails if any other role or playbook writes it again.
"""

from __future__ import annotations

import pathlib
from collections.abc import Iterator
from typing import Any

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
ANSIBLE = REPO / "infra/ansible"
OWNER = ANSIBLE / "roles/dns_resilience"
# A task that names the hosts file and the Headscale domain, by variable or literally.
HEADSCALE_MARKERS = ("headscale_domain", "vpn_domain", "headscale.domain", "vpn.kubelab.live")


def _tasks(node: Any) -> Iterator[dict[str, Any]]:
    """Every task-shaped mapping in a tasks file or playbook, nested blocks included."""
    if isinstance(node, list):
        for item in node:
            yield from _tasks(item)
    elif isinstance(node, dict):
        yield node
        for key in ("tasks", "pre_tasks", "post_tasks", "handlers", "block", "rescue", "always"):
            yield from _tasks(node.get(key))


def _delegates_to_owner(task: dict[str, Any]) -> bool:
    """A task that runs the owner role writes nothing itself (provision-jetson.yml)."""
    for key in ("include_role", "import_role", "ansible.builtin.include_role", "ansible.builtin.import_role"):
        target = task.get(key)
        if isinstance(target, dict) and str(target.get("name", "")).rstrip("/").endswith("roles/dns_resilience"):
            return True
    return False


def _writers_of_the_headscale_line() -> list[str]:
    found = []
    files = [*ANSIBLE.glob("roles/*/tasks/*.yml"), *ANSIBLE.glob("playbooks/*.yml")]
    for path in sorted(files):
        for task in _tasks(yaml.safe_load(path.read_text())):
            if _delegates_to_owner(task):
                continue
            own = {k: v for k, v in task.items() if k not in ("block", "rescue", "always", "tasks")}
            text = str(own)
            if "/etc/hosts" in text and any(m in text for m in HEADSCALE_MARKERS):
                found.append(f"{path.relative_to(REPO)}: {task.get('name', '<unnamed>')}")
    return found


def test_only_dns_resilience_writes_the_headscale_hosts_line() -> None:
    writers = _writers_of_the_headscale_line()
    owner = str(OWNER.relative_to(REPO))
    assert writers, "the scan found no writer at all: it no longer recognises the owner's task"
    assert all(w.startswith(owner) for w in writers), f"a second owner writes it: {writers}"


def test_the_scan_sees_a_second_writer(tmp_path: pathlib.Path) -> None:
    """The detector itself: a gateway-style lineinfile on the domain is caught."""
    task = {
        "name": "Ensure VPN domain resolves to public IP (/etc/hosts)",
        "lineinfile": {"path": "/etc/hosts", "line": "{{ ip }} {{ gateway_vpn_domain }}"},
    }
    text = str(next(_tasks([task])))
    assert "/etc/hosts" in text and any(m in text for m in HEADSCALE_MARKERS)
