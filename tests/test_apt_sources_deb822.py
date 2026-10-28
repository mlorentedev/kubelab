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

from tests.ansible_jinja import ansible_env

REPO = Path(__file__).resolve().parents[1]
ANSIBLE = REPO / "infra/ansible"
SOURCES_DIR = "/etc/apt/sources.list.d/"
# The file each role's old apt_repository task wrote, read on bee, ace1, ace2 and
# rpi4 on 2026-10-28. apt_repository derived the docker name from the URL and took
# `filename: github-cli` for the other, so a removal of any other path leaves it.
LEGACY_LISTS = {
    "docker": SOURCES_DIR + "download_docker_com_linux_ubuntu.list",
    "dev_node": SOURCES_DIR + "github-cli.list",
}
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
        p
        for suffix in ("*.yml", "*.yaml")
        for p in ANSIBLE.glob(f"roles/*/tasks/**/{suffix}")
        if any(_args(t, "deb822_repository") for t in _tasks(p))
    )


def test_no_task_adds_a_source_with_the_deprecated_module() -> None:
    found = [
        f"{path.relative_to(REPO)}:{text.count(chr(10), 0, match.start()) + 1}"
        for path in sorted(p for suffix in ("*.yml", "*.yaml") for p in ANSIBLE.rglob(suffix))
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
    legacy = LEGACY_LISTS[path.parts[-3]]
    removed = [
        i
        for i, t in enumerate(tasks)
        if (args := _args(t, "file")) and args.get("state") == "absent" and args.get("path") == legacy
    ]
    assert removed, f"{path.parts[-3]} writes a deb822 source and leaves {legacy} beside it"
    assert all(i > added for i in removed), "the .list goes before the .sources exists, leaving no source"
    # A tagged run that writes the source must also remove the old file.
    source_tags = set(tasks[added].get("tags", []))
    assert all(source_tags <= set(tasks[i].get("tags", [])) for i in removed), (
        "a tag writes the source and keeps the .list"
    )


@pytest.mark.parametrize("path", _deb822_task_files(), ids=lambda p: p.parts[-3])
def test_the_source_names_the_key_the_role_downloads(path: Path) -> None:
    tasks = _tasks(path)
    [added] = [i for i, t in enumerate(tasks) if _args(t, "deb822_repository")]
    signed_by = _args(tasks[added], "deb822_repository").get("signed_by")
    # A key fetched after the source leaves apt reading a source whose key is not there yet.
    keys = {str(args["dest"]) for i, t in enumerate(tasks) if i < added and (args := _args(t, "get_url"))}
    assert signed_by in keys, f"signed_by {signed_by!r} is not a key this role fetches before the source"


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
    # A tagged run reaches it before any other refresh, on a node whose index may be empty.
    assert _args(tasks[installs[0]], "apt").get("update_cache") is True, "python3-debian installs from a stale index"
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


@pytest.mark.parametrize(
    ("source", "legacy", "index", "refresh"),
    [
        (False, False, True, False),
        (True, False, True, True),
        (False, True, True, True),
        # A run that wrote the source and stopped before the install.
        (False, False, False, True),
    ],
)
def test_gh_refreshes_until_apt_has_read_its_source(source: bool, legacy: bool, index: bool, refresh: bool) -> None:
    tasks = _tasks(ANSIBLE / "roles/dev_node/tasks/main.yml")
    [install] = [args for t in tasks if (args := _args(t, "apt")) and args.get("name") == "gh"]
    rendered = (
        ansible_env(".")
        .from_string(install["update_cache"].strip())
        .render(
            dev_node_gh_source={"changed": source},
            dev_node_gh_legacy_source={"changed": legacy},
            dev_node_gh_index={"stat": {"exists": index}},
        )
    )
    assert rendered == str(refresh), rendered
