"""A play that reads `secrets` fails when it built none, unless the operator opted out (#1100).

#893 found plays that reported failed=0 and delivered no credential: a tagged run
skipped the SOPS pre_tasks, and every `| default('')` templated to empty.
`tests/test_pre_task_facts.py` keeps the load under every `--tags` that reads it.
This keeps the failure loud for what that test cannot see, such as a new play that
reads `secrets` and never loads them: each such play imports
`_includes/require-secrets.yml` with `tags: [always]`, after its load.
`allow_missing_secrets=true` is the stated way to run without them.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_image_pull_budget import PLAYBOOKS, _plays
from tests.test_pre_task_facts import _flat, _readers, _reads, _tags, _written

INCLUDE = "_includes/require-secrets.yml"
ANSIBLE_DIR = PLAYBOOKS.parent


def _requirement(play: dict) -> list[str]:
    """What is wrong with how a play that reads `secrets` requires them; empty when nothing is."""
    tasks = list(_flat(play.get("pre_tasks"), _tags(play)))
    imports = [i for i, (task, _, _) in enumerate(tasks) if task.get("import_tasks") == INCLUDE]
    if not imports:
        others = [task for task, _, _ in tasks if INCLUDE in str(task.get("include_tasks", ""))]
        return [f"includes {INCLUDE} dynamically, so --tags skips the assert"] if others else [f"no {INCLUDE}"]
    at = imports[0]
    problems = [] if "always" in tasks[at][1] else [f"{INCLUDE} without tags: [always]"]
    for i, (task, tags, _) in enumerate(tasks):
        if "secrets" not in _written(task):
            continue
        if i > at:
            problems.append(f"{INCLUDE} runs before {task.get('name')!r} builds secrets")
        if "always" not in tags:
            problems.append(f"{task.get('name')!r} lacks tags: [always], so a tagged run fails the assert")
    return problems


def test_every_play_that_reads_secrets_requires_them():
    readers = {
        f"{path}: {play.get('name')}": _requirement(play)
        for path, play in _plays()
        if any(_reads(expressions, "secrets") for _, _, expressions in _readers(play))
    }
    assert readers, "no play reads `secrets`: the detection broke, not the playbooks"
    wrong = {play: problems for play, problems in readers.items() if problems}
    assert not wrong, f"import {INCLUDE} with tags: [always] after the play's SOPS merge (#1100): {wrong}"


def test_the_requirement_sees_a_play_that_reads_secrets_without_loading_them():
    play = {
        "hosts": "rpi3",
        "pre_tasks": [{"name": "Merge configs", "set_fact": {"config": "{{ {} }}"}, "tags": ["always"]}],
        "roles": [{"role": "../roles/node_notify"}],
    }
    assert any(_reads(expressions, "secrets") for _, _, expressions in _readers(play))
    assert _requirement(play) == [f"no {INCLUDE}"]
    play["pre_tasks"].append({"import_tasks": INCLUDE, "tags": ["always"]})
    assert _requirement(play) == []
    play["pre_tasks"].append({"name": "Merge secrets", "set_fact": {"secrets": "{{ {} }}"}})
    assert _requirement(play) == [
        f"{INCLUDE} runs before 'Merge secrets' builds secrets",
        "'Merge secrets' lacks tags: [always], so a tagged run fails the assert",
    ]


def _run(tmp_path: Path, module: str, extra: dict) -> subprocess.CompletedProcess:
    """Run a local play that imports or includes the real assert, under a `--tags` that selects only its role."""
    play = [
        {
            "hosts": "localhost",
            "gather_facts": False,
            "pre_tasks": [{module: str(PLAYBOOKS / INCLUDE), "tags": ["always"]}],
            "tasks": [{"name": "The role", "ansible.builtin.debug": {"msg": "ran"}, "tags": ["role"]}],
        }
    ]
    path = tmp_path / "play.yml"
    path.write_text(json.dumps(play), encoding="utf-8")
    return subprocess.run(
        ["ansible-playbook", str(path), "-i", "localhost,", "-c", "local", "--tags", "role", "-e", json.dumps(extra)],
        cwd=ANSIBLE_DIR,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.allow_host_clients(reason="runs a play whose only host is localhost over the local connection")
@pytest.mark.parametrize(
    ("module", "extra", "fails", "says"),
    [
        ("import_tasks", {}, True, "reads `secrets` but built none"),
        ("import_tasks", {"secrets": {"a": 1}}, False, "The play built its secrets."),
        ("import_tasks", {"allow_missing_secrets": "true"}, False, "allow_missing_secrets is set"),
        # Why the import is static: an include's tags stay on the include line.
        ("include_tasks", {}, False, "ran"),
    ],
)
def test_the_assert_fails_a_play_with_no_secrets_unless_told_not_to(tmp_path, module, extra, fails, says):
    if shutil.which("ansible-playbook") is None:
        pytest.skip("ansible-playbook not on PATH: the assert was NOT run")
    result = _run(tmp_path, module, extra)
    output = result.stdout + result.stderr
    assert (result.returncode != 0) == fails, output
    assert says in output, output
