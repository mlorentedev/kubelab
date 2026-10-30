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

from tests.test_image_pull_budget import PLAYBOOKS, ROLE_MODULES, ROLES, _plays

JINJA = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
# Keys whose value is a Jinja expression without braces.
BARE = {"when", "that", "failed_when", "changed_when", "until"}
ROLE_DIRS = ("tasks", "handlers", "defaults", "vars", "templates")
IMPORTS = ("import_tasks", "include_tasks", "ansible.builtin.import_tasks", "ansible.builtin.include_tasks")


def _tags(item: dict) -> frozenset[str]:
    tags = item.get("tags") or []
    return frozenset([tags] if isinstance(tags, str) else tags)


def _flat(tasks: list | None, inherited: frozenset[str] = frozenset(), headers: tuple[dict, ...] = ()):
    """Each task with the tags it runs under and the blocks around it.

    A block's `when` and `vars` are evaluated for each task in it, under that task's tags.
    """
    for task in tasks or []:
        if not isinstance(task, dict):
            continue
        tags = inherited | _tags(task)
        if any(key in task for key in ("block", "rescue", "always")):
            header = {key: value for key, value in task.items() if key not in ("block", "rescue", "always")}
            for key in ("block", "rescue", "always"):
                yield from _flat(task.get(key), tags, (*headers, header))
        else:
            yield task, tags, headers


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


def _shared(tasks: list | None, seen: set[Path]) -> list[str]:
    """The expressions of every playbook include these tasks import, and of the includes those import."""
    expressions: list[str] = []
    for task, _, _ in _flat(tasks):
        target = next((task[module] for module in IMPORTS if isinstance(task.get(module), str)), "")
        if "{{ playbook_dir }}/" not in target:
            continue
        path = PLAYBOOKS / target.split("{{ playbook_dir }}/", 1)[1]
        if path in seen:
            continue
        seen.add(path)
        parsed = yaml.safe_load(path.read_text(encoding="utf-8"))
        expressions += _expressions(parsed)
        expressions += _shared(parsed, seen)
    return expressions


def _role(name: str) -> tuple[list[str], frozenset[str]]:
    """A role's expressions, those of the playbook includes it imports, and every tag declared on its tasks."""
    expressions: list[str] = []
    tags: set[str] = set()
    seen: set[Path] = set()
    for directory in ROLE_DIRS:
        for path in sorted((ROLES / name / directory).rglob("*")):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            if path.suffix in (".yml", ".yaml"):
                parsed = yaml.safe_load(text)
                expressions += _expressions(parsed)
                if directory in ("tasks", "handlers") and isinstance(parsed, list):
                    tags |= {tag for _, task_tags, _ in _flat(parsed) for tag in task_tags}
                    expressions += _shared(parsed, seen)
            else:
                expressions += JINJA.findall(text)
    return expressions, frozenset(tags)


def _through_vars(expressions: list[str], play_vars: dict) -> list[str]:
    """`expressions` plus those of every play var they name, transitively.

    A play var is templated when a task uses it, so what its value reads, the task reads.
    """
    found = list(expressions)
    pending = list(expressions)
    named: set[str] = set()
    while pending:
        expression = pending.pop()
        for name, value in play_vars.items():
            if name not in named and _reads([expression], name):
                named.add(name)
                more = list(_expressions(value))
                found += more
                pending += more
    return found


def _readers(play: dict):
    """(label, tags, expressions) for everything in a play that can read a pre_task's fact."""
    play_vars = play.get("vars") if isinstance(play.get("vars"), dict) else {}
    for label, tags, expressions in _direct_readers(play):
        yield label, tags, _through_vars(expressions, play_vars)


def _direct_readers(play: dict):
    base = _tags(play)
    for key in ("pre_tasks", "tasks", "post_tasks"):
        for task, tags, headers in _flat(play.get(key), base):
            yield f"{key}: {task.get('name')}", tags, list(_expressions([task, *headers]))
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
    for writer, writer_tags, _ in _flat(play.get("pre_tasks"), _tags(play)):
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
    found = {f"{path}: {play.get('name')}": unbuilt for path, play in _plays() if (unbuilt := _unbuilt(play))}
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


def test_the_resolution_follows_a_play_var_into_an_include_a_role_imports():
    """A play var is templated when a task uses it, so its reads belong to that task.

    deploy-dns.yml's coredns role reads `config` only this way: it imports
    `_includes/image-pull.yml`, which reads the play var `image_pull_down_kbit`,
    whose value reads `config`.
    """
    play = {
        "hosts": "gateway",
        "vars": {"image_pull_down_kbit": "{{ config.networking.edge.uplink.bandwidth.down_kbit }}"},
        "pre_tasks": [{"name": "Merge configs", "set_fact": {"config": "{{ {} }}"}}],
        "roles": [{"role": "../roles/coredns", "tags": ["dns"]}],
    }
    assert any("builds config, read by role coredns" in line for line in _unbuilt(play))
    play["pre_tasks"][0]["tags"] = ["always"]
    assert _unbuilt(play) == []


def test_a_play_var_that_names_another_reads_what_that_one_reads():
    play = {
        "hosts": "gateway",
        "vars": {"down": "{{ uplink.down_kbit }}", "uplink": "{{ config.networking.edge.uplink.bandwidth }}"},
        "pre_tasks": [{"name": "Merge configs", "set_fact": {"config": "{{ {} }}"}}],
        "tasks": [{"name": "Use it", "debug": {"msg": "{{ down }}"}, "tags": ["dns"]}],
    }
    assert _unbuilt(play) == ["'Merge configs' builds config, read by tasks: Use it ['dns']"]


def test_a_blocks_condition_is_read_by_each_task_in_it_under_that_tasks_tags():
    play = {
        "hosts": "gateway",
        "pre_tasks": [{"name": "Merge configs", "set_fact": {"config": "{{ {} }}"}}],
        "tasks": [{"block": [{"name": "Use it", "debug": {"msg": "ok"}, "tags": ["dns"]}], "when": "config.dns.on"}],
    }
    assert _unbuilt(play) == ["'Merge configs' builds config, read by tasks: Use it ['dns']"]
