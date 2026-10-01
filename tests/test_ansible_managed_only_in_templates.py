"""`ansible_managed` is defined only inside the `template` module.

ansible-core 2.19 stopped exposing it to other modules. A `copy:` whose inline
`content:` starts with `# {{ ansible_managed }}` now fails the task with
"'ansible_managed' is undefined". Measured on ace2 2026-10-01: the dev_node role
stopped at its Gitea ssh drop-in, so every task after it (the forge key
registration included) had not run since the controller's Ansible was upgraded.

Templates keep using it. Inline content has to write a literal header.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLES = REPO / "infra/ansible/roles"


def _walk(tasks: list | None):
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        yield task
        for nested in ("block", "rescue", "always"):
            yield from _walk(task.get(nested))


def test_no_inline_copy_content_uses_ansible_managed() -> None:
    offenders = []
    for path in sorted(ROLES.glob("*/tasks/*.yml")):
        for task in _walk(yaml.safe_load(path.read_text())):
            for key in ("ansible.builtin.copy", "copy"):
                body = task.get(key)
                if isinstance(body, dict) and "ansible_managed" in str(body.get("content", "")):
                    offenders.append(f"{path.relative_to(REPO)}: {task.get('name')}")
    assert not offenders, "ansible_managed is undefined outside `template`:\n" + "\n".join(offenders)
