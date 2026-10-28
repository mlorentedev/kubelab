"""Third-party apt sources are deb822 files, and the move leaves no second copy behind (#2737).

`apt_repository` is deprecated and goes away in ansible-core 2.25. Its successor
writes `<name>.sources`, where the old task wrote a one-line `.list`. Swapping the
module alone leaves both on every node that ran the old task: apt warns that the
target is configured more than once, and the two files can disagree on the key.
So each role that writes a deb822 source also removes, after it, the `.list` it
used to write, and keeps the key path the old line named.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
ANSIBLE = REPO / "infra/ansible"
SOURCES_DIR = "/etc/apt/sources.list.d/"
# Every spelling of the deprecated module as a task key.
APT_REPOSITORY = re.compile(r"^\s*(?:-\s+)?(?:ansible\.(?:builtin|legacy)\.)?apt_repository\s*:", re.MULTILINE)


def _args(task: dict[str, Any], module: str) -> dict[str, Any] | None:
    for key in (module, f"ansible.builtin.{module}", f"ansible.legacy.{module}"):
        if key in task:
            return task[key] or {}
    return None


def _tasks(path: Path) -> list[dict[str, Any]]:
    return [t for t in (yaml.safe_load(path.read_text(encoding="utf-8")) or []) if isinstance(t, dict)]


def _deb822_task_files() -> list[Path]:
    return sorted(
        p for p in ANSIBLE.glob("roles/*/tasks/*.yml") if any(_args(t, "deb822_repository") for t in _tasks(p))
    )


def test_no_task_adds_a_source_with_the_deprecated_module() -> None:
    found = [
        f"{path.relative_to(REPO)}:{text.count(chr(10), 0, match.start()) + 1}"
        for path in sorted(ANSIBLE.rglob("*.yml"))
        for text in [path.read_text(encoding="utf-8")]
        for match in APT_REPOSITORY.finditer(text)
    ]
    assert not found, f"apt_repository is removed in ansible-core 2.25; use deb822_repository: {found}"


def test_the_scan_reaches_both_roles_that_add_a_source() -> None:
    assert {p.parts[-3] for p in _deb822_task_files()} >= {"docker", "dev_node"}


@pytest.mark.parametrize("path", _deb822_task_files(), ids=lambda p: p.parts[-3])
def test_the_list_the_old_task_wrote_is_removed_after_the_source_is_in_place(path: Path) -> None:
    tasks = _tasks(path)
    [added] = [i for i, t in enumerate(tasks) if _args(t, "deb822_repository")]
    removed = [
        i
        for i, t in enumerate(tasks)
        if (args := _args(t, "file"))
        and args.get("state") == "absent"
        and str(args.get("path", "")).startswith(SOURCES_DIR)
        and str(args.get("path", "")).endswith(".list")
    ]
    assert removed, f"{path.parent.parent.name} writes a deb822 source and leaves the old .list beside it"
    assert all(i > added for i in removed), "the .list goes before the .sources exists, leaving no source"


@pytest.mark.parametrize("path", _deb822_task_files(), ids=lambda p: p.parts[-3])
def test_the_source_names_the_key_the_role_downloads(path: Path) -> None:
    tasks = _tasks(path)
    keys = {str(args["dest"]) for t in tasks if (args := _args(t, "get_url")) and "keyrings" in str(args.get("dest"))}
    [source] = [args for t in tasks if (args := _args(t, "deb822_repository"))]
    assert source.get("signed_by") in keys, f"signed_by {source.get('signed_by')!r} is not a key this role fetches"


@pytest.mark.parametrize("path", _deb822_task_files(), ids=lambda p: p.parts[-3])
def test_the_module_library_is_installed_first(path: Path) -> None:
    """deb822_repository imports python3-debian on the node, and a tag can skip every other role."""
    tasks = _tasks(path)
    [added] = [i for i, t in enumerate(tasks) if _args(t, "deb822_repository")]
    installs = [
        i
        for i, t in enumerate(tasks)
        if (args := _args(t, "apt")) and "python3-debian" in str(args.get("name", "")) and i < added
    ]
    assert installs, "python3-debian is not installed before the deb822 source"
    assert set(tasks[added].get("tags", [])) <= set(tasks[installs[0]].get("tags", [])), (
        "a tag that runs the source task skips the library it needs"
    )


@pytest.mark.parametrize("path", _deb822_task_files(), ids=lambda p: p.parts[-3])
def test_an_install_after_the_source_reads_the_new_index(path: Path) -> None:
    """A source apt has not read yet is invisible to the install that follows it."""
    tasks = _tasks(path)
    [added] = [i for i, t in enumerate(tasks) if _args(t, "deb822_repository")]
    refreshes = [i for i, t in enumerate(tasks) if i > added and (args := _args(t, "apt")) and args.get("update_cache")]
    assert refreshes, "nothing after the deb822 source refreshes the package index"
