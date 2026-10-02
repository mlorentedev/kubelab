"""restic is installed by one set of tasks, shared by node_backup and dev_node (BACKUP-071 AC1).

ace2 runs the restore drills, so it needs the same pinned, checksum-verified
restic the backup nodes ship with. A second copy of the install would drift:
one role bumps the version or fixes the decompress step, the other does not,
and a drill then reads a repository with a different restic than wrote it.
These tests fail if either role grows its own copy.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parent.parent
ROLES = REPO / "infra/ansible/roles"
SHARED = ROLES / "node_backup/tasks/restic.yml"


def _tasks(path: Path) -> list[dict[str, Any]]:
    """Every task in a file, blocks flattened."""
    out: list[dict[str, Any]] = []
    for task in yaml.safe_load(path.read_text()) or []:
        out.append(task)
        for key in ("block", "rescue", "always"):
            out.extend(task.get(key) or [])
    return out


def _downloads_restic(task: dict[str, Any]) -> bool:
    get_url = task.get("get_url") or task.get("ansible.builtin.get_url") or {}
    return "restic_" in str(get_url.get("url", ""))


#: Modules that put a binary on a host. A task naming restic in one of them, outside
#: the shared file, is a second install. Checked by module, never by task name: the
#: `import_tasks: restic.yml` and `import_role ... tasks_from: restic` that wire the
#: shared file in also say "restic" and acquire nothing.
_PACKAGE_MODULES = ("apt", "package", "dnf", "yum", "snap", "pip", "community.general.snap")
_FILE_MODULES = ("get_url", "unarchive", "copy")
_SHELL_MODULES = ("shell", "command", "raw")
#: Tools that fetch or unpack. A shell task that runs restic (`restic version`,
#: `restic init`) is not an install; one that pipes curl into a restic path is.
_FETCHERS = re.compile(r"\b(curl|wget|apt(-get)?|snap|pip3?|dpkg|tar|bunzip2|bzip2|unzip|install)\b")


def _is_binary(dest: Any) -> bool:
    """A destination that is the restic executable itself, not a file restic uses (its password, its cache)."""
    text = str(dest or "")
    return bool(re.search(r"(^|/)restic$", text)) or "restic_install_path" in text


def _module_args(task: dict[str, Any], short: str) -> Any:
    for key in (short, f"ansible.builtin.{short}", f"community.general.{short}"):
        if key in task:
            return task[key]
    return None


def _acquires_restic(task: dict[str, Any]) -> bool:
    """True when the task installs, downloads, unpacks or copies a restic binary, by any module."""
    for module in _PACKAGE_MODULES:
        args = _module_args(task, module)
        if args is not None:
            name = args.get("name") if isinstance(args, dict) else args
            names = name if isinstance(name, list) else [name]
            if any("restic" in str(n) for n in names):
                return True
    for module in _FILE_MODULES:
        args = _module_args(task, module)
        if isinstance(args, dict) and (
            "restic" in str(args.get("url", "")) or "restic" in str(args.get("src", "")) or _is_binary(args.get("dest"))
        ):
            return True
    for module in _SHELL_MODULES:
        args = _module_args(task, module)
        if args is not None:
            text = str(args.get("cmd") or args.get("argv") or "") if isinstance(args, dict) else str(args)
            if "restic" in text and _FETCHERS.search(text):
                return True
    return False


def test_the_shared_file_downloads_restic_at_the_pinned_version() -> None:
    downloads = [t for t in _tasks(SHARED) if _downloads_restic(t)]
    assert len(downloads) == 1, f"{SHARED.name} must hold the one restic download"
    url = str((downloads[0].get("get_url") or downloads[0].get("ansible.builtin.get_url"))["url"])
    assert "node_backup_restic_version" in url, "the version comes from backup.r2.restic_version, never a literal"


def test_node_backup_includes_the_shared_file() -> None:
    main = _tasks(ROLES / "node_backup/tasks/main.yml")
    includes = [t for t in main if (t.get("import_tasks") or t.get("ansible.builtin.import_tasks")) == "restic.yml"]
    assert len(includes) == 1, "node_backup must import restic.yml exactly once"


def test_dev_node_imports_the_same_file_through_node_backup() -> None:
    found = []
    for path in sorted((ROLES / "dev_node/tasks").glob("*.yml")):
        for task in _tasks(path):
            inc = task.get("import_role") or task.get("ansible.builtin.import_role") or {}
            if str(inc.get("name", "")).endswith("node_backup") and inc.get("tasks_from") == "restic":
                found.append((path.name, task))
    assert len(found) == 1, (
        "dev_node must import node_backup's restic tasks exactly once (import_role, so syntax-check resolves it)"
    )
    _, task = found[0]
    assert "node_backup_restic_version" in (task.get("vars") or {}), "dev_node must pass the pinned version in"


def test_no_other_task_file_downloads_restic() -> None:
    offenders = [
        f"{path.relative_to(REPO)}: {task.get('name')}"
        for role in ("node_backup", "dev_node")
        for path in sorted((ROLES / role / "tasks").glob("*.yml"))
        if path != SHARED
        for task in _tasks(path)
        if _acquires_restic(task)
    ]
    assert not offenders, f"a second restic install will drift from the shared one: {offenders}"
