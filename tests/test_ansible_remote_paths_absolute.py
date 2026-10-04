"""A path on a managed node never starts with `~` (ANSIBLE-064, #2053).

A remote `~` is the home of whoever the task runs as, so the same role writes to
`/home/<user>/...` without `become` and to `/root/...` with it. The coredns role
kept the DNS gateway stack in `~/coredns`; deploy-dns.yml (no `become`) and
provision-rpi4.yml (`become: true`) each moved the containers to their own copy.
lesson-242 is the same mechanism for buildx state.

`~` stays legitimate on the controller, where it is the operator's home and
`become` does not apply (the fetched kubeconfig). So the rule is about where a
task runs, read from the task, its block or its play, never from a comment.
"""

from __future__ import annotations

import pathlib
import re
from collections.abc import Iterator
from typing import Any

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
ANSIBLE = REPO / "infra/ansible"
TASK_LISTS = ("pre_tasks", "tasks", "post_tasks", "handlers")
CHILDREN = ("block", "rescue", "always")
CONTROLLER = {"localhost", "127.0.0.1"}
# Text shown to a person, not a path the task touches (dev_node's fail_msg names ~/.gitconfig).
PROSE = {"msg", "fail_msg", "success_msg"}
# `~/` at the start of a value or after a separator. Jinja's `~` operator is
# followed by a space or a quote, never by `/`, so concatenation does not match.
TILDE = re.compile(r"""(?:^|[\s'"=:(,])~(?:/|$)""")


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for key, value in node.items():
            if key not in PROSE:
                yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)


def _tilde_vars(root: pathlib.Path) -> set[str]:
    """Every variable whose value is a `~` path, wherever it is defined."""
    names: set[str] = set()

    def collect(mapping: Any) -> None:
        if isinstance(mapping, dict):
            names.update(k for k, v in mapping.items() if isinstance(v, str) and TILDE.search(v))

    for path in [*root.glob("roles/*/defaults/**/*.y*ml"), *root.glob("roles/*/vars/**/*.y*ml")]:
        collect(yaml.safe_load(path.read_text()))
    for path in root.glob("playbooks/**/*.y*ml"):
        for play in yaml.safe_load(path.read_text()) or []:
            collect(play.get("vars"))
            for role in play.get("roles") or []:
                if isinstance(role, dict):
                    collect(role.get("vars"))
            for task, _ in _tasks_in_play(play):
                collect(task.get("vars"))
    return names


def _on_controller(node: dict[str, Any], inherited: bool) -> bool:
    if node.get("connection") == "local":
        return True
    if "delegate_to" in node:
        return str(node["delegate_to"]) in CONTROLLER
    return inherited


def _walk(tasks: Any, on_controller: bool) -> Iterator[tuple[dict[str, Any], bool]]:
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        here = _on_controller(task, on_controller)
        yield task, here
        for key in CHILDREN:
            yield from _walk(task.get(key), here)


def _tasks_in_play(play: dict[str, Any]) -> Iterator[tuple[dict[str, Any], bool]]:
    hosts = play.get("hosts")
    on_controller = _on_controller(play, isinstance(hosts, str) and hosts in CONTROLLER)
    for key in TASK_LISTS:
        yield from _walk(play.get(key), on_controller)


def _all_tasks(root: pathlib.Path) -> Iterator[tuple[pathlib.Path, dict[str, Any], bool]]:
    for path in [*root.glob("roles/*/tasks/**/*.y*ml"), *root.glob("roles/*/handlers/**/*.y*ml")]:
        for task, here in _walk(yaml.safe_load(path.read_text()), False):
            yield path, task, here
    for path in root.glob("playbooks/**/*.y*ml"):
        for play in yaml.safe_load(path.read_text()) or []:
            for task, here in _tasks_in_play(play):
                yield path, task, here


def _remote_tilde_paths(root: pathlib.Path = ANSIBLE) -> list[str]:
    """Tasks on a managed node that use a `~` path, literally or through a variable."""
    tilde_vars = _tilde_vars(root)
    uses = re.compile(r"\b(" + "|".join(map(re.escape, sorted(tilde_vars))) + r")\b") if tilde_vars else None
    found = []
    for path, task, on_controller in _all_tasks(root):
        if on_controller:
            continue
        own = {k: v for k, v in task.items() if k not in (*CHILDREN, "vars", "name")}
        text = list(_strings(own))
        if any(TILDE.search(s) for s in text) or (uses and any(uses.search(s) for s in text)):
            found.append(f"{path.relative_to(root)}: {task.get('name', '<unnamed>')}")
    return sorted(found)


def test_no_task_on_a_managed_node_uses_a_tilde_path() -> None:
    found = _remote_tilde_paths()
    assert not found, (
        "`~` on a managed node is the home of whoever the task runs as, so it differs with "
        f"and without `become` (ANSIBLE-064). Use an absolute path: {found}"
    )


def test_the_scan_reports_every_way_a_remote_tilde_hides(tmp_path: pathlib.Path) -> None:
    files: dict[str, Any] = {
        "roles/svc/defaults/main.yml": {"svc_dir": "~/svc", "svc_kubeconfig": "~/.kube/c", "svc_abs": "/opt/svc"},
        "roles/svc/tasks/main.yml": [
            {"name": "via default", "file": {"path": "{{ svc_dir }}", "state": "directory"}},
            {"name": "literal", "command": "cat ~/notes"},
            {"name": "absolute", "file": {"path": "{{ svc_abs }}"}},
            {"name": "jinja concat", "set_fact": {"svc_sub": "{{ svc_abs ~ '/x' }}"}},
            {"name": "prose", "assert": {"that": ["true"], "fail_msg": "check ~/.gitconfig"}},
            {"name": "fetched", "fetch": {"dest": "{{ svc_kubeconfig }}"}, "delegate_to": "localhost"},
            {"name": "outer", "delegate_to": "localhost", "block": [{"name": "inherited", "stat": {"path": "~/x"}}]},
            {"name": "remote block", "become": True, "block": [{"name": "nested", "copy": {"dest": "~/y"}}]},
        ],
        "playbooks/site.yml": [
            {
                "hosts": "all",
                "vars": {"site_dir": "~/site"},
                "tasks": [{"name": "play var", "file": {"path": "{{ site_dir }}"}}],
            },
            {"hosts": "localhost", "tasks": [{"name": "controller play", "stat": {"path": "~/.kube/c"}}]},
        ],
    }
    for rel, content in files.items():
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(yaml.safe_dump(content))

    found = {line.split(": ", 1)[1] for line in _remote_tilde_paths(tmp_path)}

    assert found == {"via default", "literal", "nested", "play var"}
