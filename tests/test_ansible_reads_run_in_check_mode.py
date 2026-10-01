"""Every read in every role runs under `--check` (ANSIBLE-059, #1978).

Check mode skips `command` and `shell` tasks, and a skipped task registers no
`rc` and no `stdout`. A read (a registered command that never reports a change)
then hands its consumer nothing: an assert fails on an empty string, a
`set_fact` dies on a missing `.rc`, a URL loses its query. Lessons 392 and 397
record the class, and it recurred three times on ace2 on 2026-10-01 after both
were written.

Whether a given read breaks a dry run depends on whether something reads its
register later, and that is the judgement readers get wrong. The rule here does
not ask it: a read has no side effect by definition, so running it under
`--check` is always safe, and every read declares `check_mode: false`.

The shape is not proof: a task can report no change and still write. Those are
declared below by name, so the exemption is a reviewed decision and not a gap.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLES = REPO / "infra/ansible/roles"

COMMAND_MODULES = ("ansible.builtin.command", "command", "ansible.builtin.shell", "shell")

# Writes that report no change, so they look like reads. `--check` must keep
# skipping them: `check_mode: false` would make a dry run perform them.
# Keyed by (role, task name), each with the reason it reports no change.
WRITES_THAT_REPORT_NO_CHANGE = {
    ("node_maintenance", "Hold packages whose upgrade would restart a live workload"): (
        "the run releases every hold it creates, so the node ends where it began"
    ),
    ("docker", "Test Docker functionality"): (
        "a smoke test: it pulls hello-world and runs a container, which a dry run must not"
    ),
}


def _flatten(tasks: list[dict] | None) -> list[dict]:
    """Every task, including those nested in a block, rescue or always."""
    flat: list[dict] = []
    for task in tasks or []:
        flat.append(task)
        for section in ("block", "rescue", "always"):
            flat.extend(_flatten(task.get(section)))
    return flat


def _is_read(task: dict) -> bool:
    return (
        any(key in task for key in COMMAND_MODULES)
        and bool(task.get("register"))
        and task.get("changed_when") in (False, "false")
    )


def _role(path: str) -> str:
    return path.split("/")[3]


def _candidates() -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    for path in sorted(ROLES.glob("*/tasks/*.yml")):
        for task in _flatten(yaml.safe_load(path.read_text())):
            if _is_read(task):
                found.append((str(path.relative_to(REPO)), task))
    return found


def _reads() -> list[tuple[str, dict]]:
    return [(p, t) for p, t in _candidates() if (_role(p), t.get("name")) not in WRITES_THAT_REPORT_NO_CHANGE]


def test_the_guard_finds_reads() -> None:
    """A guard that matches nothing passes on any tree (lesson-497)."""
    roles = {_role(path) for path, _ in _reads()}
    assert len(roles) >= 5, f"only {sorted(roles)} hold reads; the matcher is broken"


def test_every_read_runs_in_a_dry_run() -> None:
    skipped = [
        f"{path}: {task.get('name', '<unnamed>')}" for path, task in _reads() if task.get("check_mode") is not False
    ]
    assert not skipped, "reads skipped by --check (add `check_mode: false`):\n  " + "\n  ".join(skipped)


def test_every_declared_write_still_exists_and_stays_skipped() -> None:
    """An exemption whose task was renamed or removed exempts nothing and hides nothing; drop it."""
    candidates = {(_role(p), t.get("name")): t for p, t in _candidates()}
    for key in WRITES_THAT_REPORT_NO_CHANGE:
        assert key in candidates, f"{key} is declared a write but no such read-shaped task exists"
        assert candidates[key].get("check_mode") is not False, f"{key} is a write and must not run under --check"
