"""Restore a node's file-and-SQLite sources from its own repository and prove they came back whole (BACKUP-076).

`backup.sources.<node>` declares what `node_backup` captures: a directory per
source, SQLite databases snapshotted with `.backup`, and `exclude` paths ruled
not worth keeping. The application drills each know one service; this one knows
only that declaration, so any node whose sources have that shape can be drilled
(ace2 is the first). For each source it restores the node's newest snapshot into
a scratch directory, never over a live path, and passes only if:

- the source restored at least one file;
- every declared database is there and `PRAGMA integrity_check` answers `ok`;
- every declared `exclude` path is absent: one that came back means the capture
  read what it was told not to.

A `pg_dumpall` source is not this shape and has `drill-postgres`; it is named
and skipped.

The restore holds credentials and sessions (Open WebUI's `webui.db`, Hermes's
state). Only declared names, counts, sizes and timings are printed, never a
walked file name or any content, and the directory is removed on every exit
path. No container is started, so docker is not needed.
"""

from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional

from toolkit.core.logging import logger
from toolkit.features.headscale_drill import sqlite_intact
from toolkit.features.restore_drill import latest_snapshot, report, restore_source, scratch

Run = Callable[..., "tuple[int, str, str]"]


@dataclass(frozen=True)
class Want:
    """What a source's declaration says must be true of its restore."""

    sqlite: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()


def _default_run(argv: list[str], *, env: Optional[dict[str, str]] = None) -> tuple[int, str, str]:
    proc = subprocess.run(argv, capture_output=True, text=True, env={**os.environ, **(env or {})}, check=False)
    return proc.returncode, proc.stdout, proc.stderr


def _inside(path: str) -> bool:
    """A declared path names something under its source, never above it or elsewhere."""
    parts = PurePosixPath(path).parts
    return bool(parts) and not PurePosixPath(path).is_absolute() and ".." not in parts


def _plan(sources: dict[str, Any], label: str) -> Optional[dict[str, Want]]:
    """The sources to check and what each must satisfy, or None after naming why none can be."""
    plan: dict[str, Want] = {}
    for name, spec in sorted(sources.items()):
        spec = spec or {}
        if "pg_dumpall" in spec:
            logger.info(f"{label}: {name}: skipped, a logical dump (drill-postgres restores it)")
            continue
        databases = spec.get("sqlite") or []
        databases = [databases] if isinstance(databases, str) else list(databases)
        excluded = list(spec.get("exclude") or {})
        for path in (*databases, *excluded):
            if not _inside(str(path)):
                logger.error(f"{label}: CANNOT CHECK — {name}: {path} is outside its source")
                return None
        plan[name] = Want(tuple(map(str, databases)), tuple(map(str, excluded)))
    if not plan:
        logger.error(f"{label}: CANNOT CHECK — backup.sources declares no file or SQLite source for this node")
        return None
    return plan


def _tally(data: Path) -> tuple[int, int]:
    """Files (symlinks included) under `data` and their total size in bytes."""
    count = size = 0
    for root, dirs, files in os.walk(data):
        links = [d for d in dirs if os.path.islink(os.path.join(root, d))]
        for entry in (*files, *links):
            count += 1
            size += os.lstat(os.path.join(root, entry)).st_size
    return count, size


def check_source(name: str, data: Path, want: Want) -> tuple[bool, list[str]]:
    """Compare a restored source with its declaration. Only declared names are ever printed."""
    lines: list[str] = []
    ok = True
    count, size = _tally(data)
    lines.append(f"{name}: {count} file{'' if count == 1 else 's'}, {size} bytes")
    if count == 0:
        ok = False
        lines.append(f"FAIL {name}: restored no file")
    for database in want.sqlite:
        if not (data / database).is_file():
            ok = False
            lines.append(f"FAIL {name}: {database}: declared database is missing from the restore")
        elif sqlite_intact(data / database):
            lines.append(f"{name}: {database}: integrity_check ok")
        else:
            ok = False
            lines.append(f"FAIL {name}: {database}: PRAGMA integrity_check did not answer ok")
    for path in want.exclude:
        if os.path.lexists(data / path):
            ok = False
            lines.append(f"FAIL {name}: {path}: declared exclude is present in the restore")
        else:
            lines.append(f"{name}: {path}: absent")
    return ok, lines


def run_drill(
    *,
    node: str,
    sources: dict[str, Any],
    repo: str,
    restic_env: dict[str, str],
    staging_dir: str,
    run: Run = _default_run,
    clock: Callable[[], float] = time.monotonic,
) -> bool:
    """Restore `node`'s newest capture in `repo` and check each declared source. True only on a whole restore."""
    label = f"drill: {node}"
    plan = _plan(sources, label)
    if plan is None:
        return False
    snapshot = latest_snapshot(run, repo, restic_env, label=label)
    if snapshot is None:
        return False

    ok = True
    with scratch(run, "nodedrill", holds=f"{node}'s files, which can hold credentials", container=False) as box:
        started = clock()
        for name, want in plan.items():
            restored_at = clock()
            data = restore_source(
                run,
                repo=repo,
                restic_env=restic_env,
                snapshot=snapshot["short_id"],
                source=f"{staging_dir}/{name}",
                workdir=box.workdir,
                label=label,
            )
            if data is None:
                logger.error(f"{label}: FAIL {name}: not restored")
                ok = False
                continue
            checked_at = clock()
            passed, lines = check_source(name, data, want)
            report(lines, prefix=f"{label}: ")
            logger.info(
                f"{label}: {name}: restored in {checked_at - restored_at:.0f}s, checked in {clock() - checked_at:.0f}s"
            )
            ok = passed and ok
        logger.info(f"{label}: RTO {clock() - started:.0f}s for {len(plan)} source(s)")
        if ok:
            logger.success(f"{label}: snapshot {snapshot['short_id']} restores {', '.join(plan)} completely")
    # A restore that passed but left its files behind is not a pass.
    return ok and box.clean


def drill_node(node: str, env: str = "prod", project_root: Optional[Path] = None) -> bool:
    """Resolve the node's repository, credentials and declared sources from the SSOT and run the drill."""
    from toolkit.features.backup_destination import DestinationError, node_restic
    from toolkit.features.configuration import ConfigurationManager
    from toolkit.features.postgres_drill import staging_dir

    cm = ConfigurationManager(env, project_root)
    root = Path(project_root or cm.project_root)
    logger.section(f"{node} restore drill — newest capture in its repository into a scratch directory ({env})")
    sources = ((cm.get_merged_config().get("backup", {}) or {}).get("sources", {}) or {}).get(node)
    if not sources:
        logger.error(f"drill: {node}: CANNOT CHECK — backup.sources declares nothing for {node}")
        return False
    try:
        repo, restic_env = node_restic(cm, node)
    except DestinationError as exc:
        logger.error(f"drill: {node}: CANNOT CHECK — {exc}")
        return False
    return run_drill(
        node=node,
        sources=sources,
        repo=repo,
        restic_env=restic_env,
        staging_dir=staging_dir(root),
    )
