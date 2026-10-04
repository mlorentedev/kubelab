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
OWNER = "roles/dns_resilience"
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
        # Both forms Ansible accepts: the bare role name and a relative path to it.
        if isinstance(target, dict) and str(target.get("name", "")).rstrip("/").split("/")[-1] == "dns_resilience":
            return True
    return False


WHOLE_FILE = ("template", "copy", "ansible.builtin.template", "ansible.builtin.copy")


def _replaces_the_hosts_file(task: dict[str, Any]) -> bool:
    """A task that renders the whole file writes every line in it, the Headscale one included,
    whatever its source says, and overwrites the owner's block on each run."""
    return any(isinstance(task.get(k), dict) and task[k].get("dest") == "/etc/hosts" for k in WHOLE_FILE)


def _writers_of_the_headscale_line(root: pathlib.Path = ANSIBLE) -> list[str]:
    """Writers under `root`, as paths relative to it: role tasks and handlers, and playbooks."""
    found = []
    patterns = ("roles/*/tasks/**/*.y*ml", "roles/*/handlers/**/*.y*ml", "playbooks/**/*.y*ml")
    files = {f for pattern in patterns for f in root.glob(pattern)}
    for path in sorted(files):
        for task in _tasks(yaml.safe_load(path.read_text())):
            if _delegates_to_owner(task):
                continue
            own = {k: v for k, v in task.items() if k not in ("block", "rescue", "always", "tasks")}
            text = str(own)
            if _replaces_the_hosts_file(task) or ("/etc/hosts" in text and any(m in text for m in HEADSCALE_MARKERS)):
                found.append(f"{path.relative_to(root)}: {task.get('name', '<unnamed>')}")
    return found


def test_only_dns_resilience_writes_the_headscale_hosts_line() -> None:
    writers = _writers_of_the_headscale_line()
    assert writers, "the scan found no writer at all: it no longer recognises the owner's task"
    assert all(w.startswith(OWNER) for w in writers), f"a second owner writes it: {writers}"


def test_the_scan_sees_a_second_writer(tmp_path: pathlib.Path) -> None:
    """The scan itself, on a fixture tree: every place a writer can hide is reported,
    and a task that runs the owner role, in either form, is not."""
    writer = [
        {"name": "Pin VPN domain", "lineinfile": {"path": "/etc/hosts", "line": "{{ ip }} {{ gateway_vpn_domain }}"}}
    ]
    # Shaped like provision-jetson.yml's: they name the hosts file and pass the domain.
    owner_vars = {"headscale_domain": "{{ domain }}"}
    delegations = [
        {
            "hosts": "all",
            "tasks": [
                {"name": "DNS in /etc/hosts", "include_role": {"name": "../roles/dns_resilience"}, "vars": owner_vars},
                {"name": "DNS in /etc/hosts", "import_role": {"name": "dns_resilience"}, "vars": owner_vars},
            ],
        },
    ]
    files = {
        "roles/dns_resilience/tasks/main.yml": writer,
        "roles/gateway/tasks/main.yml": writer,
        "roles/gateway/tasks/nested/dns.yaml": writer,
        "roles/gateway/handlers/main.yml": writer,
        "roles/net/tasks/main.yml": [{"name": "Render hosts", "template": {"src": "hosts.j2", "dest": "/etc/hosts"}}],
        "playbooks/provision-x.yml": [{"hosts": "all", "tasks": [{"block": writer}]}],
        "playbooks/delegates.yml": delegations,
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(yaml.safe_dump(content))

    found = {line.split(":")[0] for line in _writers_of_the_headscale_line(tmp_path)}

    assert found == set(files) - {"playbooks/delegates.yml"}
