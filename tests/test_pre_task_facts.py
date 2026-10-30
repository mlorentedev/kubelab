"""A fact a play's pre_tasks build is built under every `--tags` that runs a reader of it (#2817).

Under `--tags x` Ansible runs only what carries `x` or `always`. An untagged
pre_task that builds `config` or `secrets` is skipped, while a role tagged `x`
still runs and fails on the undefined fact. lesson-325 fixed four playbooks by
hand and `deploy-vps.yml` was not among them, so this reads every play.

A reader is a role (its tasks, templates, defaults, vars and handlers), a task, or
another pre_task. Its tags are those that select it: a role's include every tag
declared inside it, since `--tags gitea` runs that part of the role alone. The
writer needs `always` unless every tag that selects the reader also selects it.
Only `--tags` is covered: `--skip-tags` can drop any tagged task by design.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from tests.test_image_pull_budget import ROLE_MODULES, ROLES, _plays

JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
# Keys whose value is a Jinja expression without braces.
BARE = {"when", "that", "failed_when", "changed_when", "until"}
ROLE_DIRS = ("tasks", "handlers", "defaults", "vars", "templates")


def _tags(item: dict) -> frozenset[str]:
    tags = item.get("tags") or []
    return frozenset([tags] if isinstance(tags, str) else tags)


def _flat(tasks: list | None, inherited: frozenset[str] = frozenset()):
    """Each task with the tags it runs under, a block's included."""
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        tags = inherited | _tags(task)
        if any(key in task for key in ("block", "rescue", "always")):
            for key in ("block", "rescue", "always"):
                yield from _flat(task.get(key), tags)
        else:
            yield task, tags


def _expressions(node, key: str | None = None):
    if isinstance(node, dict):
        for child_key, value in node.items():
            yield from _expressions(value, child_key)
    elif isinstance(node, list):
        for value in node:
            yield from _expressions(value, key)
    elif isinstance(node, str):
        if key in BARE:
            yield node
        yield from JINJA.findall(node)


def _written(task: dict) -> set[str]:
    names = set()
    for module in ("set_fact", "ansible.builtin.set_fact"):
        if isinstance(task.get(module), dict):
            names |= set(task[module]) - {"cacheable"}
    for module in ("include_vars", "ansible.builtin.include_vars"):
        if isinstance(task.get(module), dict) and task[module].get("name"):
            names.add(task[module]["name"])
    if task.get("register"):
        names.add(task["register"])
    return names


def _role(name: str) -> tuple[list[str], frozenset[str]]:
    """A role's expressions, and every tag declared on its tasks."""
    expressions: list[str] = []
    tags: set[str] = set()
    for directory in ROLE_DIRS:
        for path in sorted((ROLES / name / directory).rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if path.suffix in (".yml", ".yaml"):
                parsed = yaml.safe_load(text)
                expressions += _expressions(parsed)
                if directory in ("tasks", "handlers") and isinstance(parsed, list):
                    tags |= {tag for _, task_tags in _flat(parsed) for tag in task_tags}
            else:
                expressions += JINJA.findall(text)
    return expressions, frozenset(tags)


def _readers(play: dict):
    """(label, tags, expressions) for everything in a play that can read a pre_task's fact."""
    base = _tags(play)
    for key in ("pre_tasks", "tasks", "post_tasks"):
        for task, tags in _flat(play.get(key), base):
            yield f"{key}: {task.get('name')}", tags, list(_expressions(task))
            for module in ROLE_MODULES:
                if isinstance(task.get(module), dict):
                    name = Path(task[module]["name"]).name
                    expressions, inner = _role(name)
                    yield f"role {name}", tags | inner, expressions
    for entry in play.get("roles") or []:
        entry = entry if isinstance(entry, dict) else {"role": entry}
        name = Path(entry["role"]).name
        expressions, inner = _role(name)
        own = {key: value for key, value in entry.items() if key != "role"}
        yield f"role {name}", base | _tags(entry) | inner, expressions + list(_expressions(own))


def _reads(expressions: list[str], name: str) -> bool:
    pattern = re.compile(rf"(?<![\w.]){re.escape(name)}\b")
    return any(pattern.search(expression) for expression in expressions)


def _unbuilt(play: dict) -> list[str]:
    readers = list(_readers(play))
    found = []
    for writer, writer_tags in _flat(play.get("pre_tasks"), _tags(play)):
        if "always" in writer_tags:
            continue
        for name in sorted(_written(writer)):
            for label, tags, expressions in readers:
                if not tags or not _reads(expressions, name):
                    continue
                if "always" in tags or not tags <= writer_tags:
                    found.append(f"{writer.get('name')!r} builds {name}, read by {label} {sorted(tags)}")
    return found


def test_a_play_builds_its_facts_under_every_tag_that_reads_them():
    found = {
        f"{path}: {play.get('name')}": unbuilt for path, play in _plays() if (unbuilt := _unbuilt(play))
    }
    assert not found, (
        "these pre_tasks are skipped by a `--tags` that still runs a reader of what they build; "
        f"give them `tags: [always]` (lesson-325): {found}"
    )


def test_the_resolution_sees_an_untagged_fact_read_by_a_tagged_role():
    play = {
        "hosts": "vps",
        "pre_tasks": [
            {"name": "Load base config", "include_vars": {"file": "common.yaml", "name": "common"}},
            {"name": "Merge configs", "set_fact": {"config": "{{ common }}"}, "tags": ["always"]},
        ],
        "roles": [{"role": "headscale", "tags": ["headscale"], "vars": {"domain": "{{ config.global.base_domain }}"}}],
    }
    assert _unbuilt(play) == ["'Load base config' builds common, read by pre_tasks: Merge configs ['always']"]
    del play["pre_tasks"][1]["tags"]
    assert any("builds config, read by role headscale" in line for line in _unbuilt(play))
