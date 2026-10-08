"""The phases every restore drill shares (BACKUP-072, #2015).

Each drill restores the newest capture into a scratch directory and a scratch
container, checks it against live, and removes both. Choosing the snapshot,
restoring it, waiting for the scratch server and tearing it down were copied
into four modules, and the copies drifted apart: two drills raised on a
snapshot list the other two reported as CANNOT CHECK, and one took the first
snapshot where the others took the last (lesson-505). Those phases live here
once.
"""

from __future__ import annotations

import json
import secrets
import shutil
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Optional

from toolkit.core.logging import logger

Run = Callable[..., "tuple[int, str, str]"]

#: The named volumes a container mounts, space-separated.
_VOLUMES_FORMAT = '{{range .Mounts}}{{if eq .Type "volume"}}{{.Name}} {{end}}{{end}}'


def _snapshot_list(rc: int, out: str, err: str) -> tuple[list[Any], str]:
    """What `restic snapshots --json` answered, and why it cannot be used if it is empty."""
    if rc != 0:
        return [], err.strip()[:160]
    try:
        parsed = json.loads(out or "[]")
    except ValueError:
        return [], "the snapshot list could not be parsed"
    if not isinstance(parsed, list):
        return [], "the snapshot list is not a list"
    return parsed, "the repository holds no snapshot"


def _usable(snapshot: Any) -> bool:
    return isinstance(snapshot, dict) and all(isinstance(snapshot.get(k), str) for k in ("short_id", "time"))


def latest_snapshot(run: Run, repo: str, restic_env: dict[str, str], label: str = "drill") -> Optional[dict[str, Any]]:
    """The newest snapshot in `repo`, or None after naming why there is none to restore.

    `--latest 1` answers one snapshot per host and path group. Every capture
    today stages one path, so one group comes back (measured 2026-10-02 on the
    vps and beelink repositories). More than one means the repository holds
    captures of different path sets, and choosing between them by position is
    how the drills came to disagree, so that is CANNOT CHECK as well.
    """
    rc, out, err = run(["restic", "-r", repo, "snapshots", "--json", "--latest", "1"], env=restic_env)
    snapshots, reason = _snapshot_list(rc, out, err)
    if snapshots and not all(map(_usable, snapshots)):
        snapshots, reason = [], "a snapshot lacks its id or its time"
    if not snapshots:
        logger.error(f"{label}: CANNOT CHECK — no snapshot readable in {repo}: {reason}")
        return None
    if len(snapshots) > 1:
        groups = "; ".join(f"{s.get('hostname')} {s.get('paths')}" for s in snapshots)
        logger.error(f"{label}: CANNOT CHECK — {repo} holds {len(snapshots)} capture groups ({groups})")
        return None
    snapshot: dict[str, Any] = snapshots[0]
    logger.info(f"{label}: snapshot {snapshot['short_id']} taken {snapshot['time']}")
    return snapshot


def restore_source(
    run: Run,
    *,
    repo: str,
    restic_env: dict[str, str],
    snapshot: str,
    source: str,
    workdir: Path,
    required: str = "",
    label: str = "drill",
) -> Optional[Path]:
    """Restore `source` from `snapshot` under `workdir` and return where it landed, or None.

    The snapshot stores absolute paths, so the data lands at `workdir/source`.
    With `required`, that file must be in it; otherwise the directory must exist.
    """
    rc, _, err = run(
        ["restic", "-r", repo, "restore", snapshot, "--include", source, "--target", str(workdir)],
        env=restic_env,
    )
    data = workdir / source.lstrip("/")
    landed = (data / required).is_file() if required else data.is_dir()
    if rc != 0 or not landed:
        what = f"{source}/{required}" if required else source
        logger.error(f"{label}: restic could not restore {what}: {err.strip()[:160]}")
        return None
    return data


def wait_until(
    ready: Callable[[], bool],
    *,
    timeout: float,
    sleep: Callable[[float], None],
    clock: Callable[[], float],
    interval: float = 1,
) -> bool:
    """Poll `ready` until it answers True, or False once `timeout` seconds have passed."""
    deadline = clock() + timeout
    while not ready():
        if clock() > deadline:
            return False
        sleep(interval)
    return True


def report(lines: list[str], prefix: str = "") -> None:
    """Log a comparison: FAIL lines as errors, the rest as information."""
    for line in lines:
        (logger.error if line.startswith("FAIL") else logger.info)(f"{prefix}{line}")


def remove_scratch_container(run: Run, name: str) -> bool:
    """Remove a drill's container with its volumes, then confirm both are gone.

    `-v` is the data: an image that declares a VOLUME (postgres, gitea) keeps the
    restored database in an anonymous volume that outlives a plain `docker rm`
    (lesson-498). The exit code of `docker rm` cannot tell a removal that failed
    from one that had nothing to remove, since both are non-zero, so the answer
    is read back: the container must be unknown to docker, and so must each
    volume it mounted.
    """
    rc, out, _ = run(["docker", "container", "inspect", "-f", _VOLUMES_FORMAT, name])
    volumes = out.split() if rc == 0 else []
    run(["docker", "rm", "-f", "-v", name])
    left = []
    rc, _, err = run(["docker", "container", "inspect", name])
    if rc == 0 or "no such container" not in err.lower():
        left.append(f"container {name}")
    for volume in volumes:
        rc, _, err = run(["docker", "volume", "inspect", volume])
        if rc == 0 or "no such volume" not in err.lower():
            left.append(f"volume {volume}")
    if left:
        logger.error(
            f"drill: restored data is still on this machine ({', '.join(left)}): "
            f"remove it now with `docker rm -f -v {name}` and `docker volume rm` on each volume"
        )
    return not left


def _rmtree(workdir: Path) -> bool:
    shutil.rmtree(workdir, ignore_errors=True)
    return not workdir.exists()


@dataclass
class Scratch:
    """A drill's scratch directory and container name. `clean` is set when the drill ends."""

    workdir: Path
    name: str
    clean: bool = False


@contextmanager
def scratch(
    run: Run,
    prefix: str,
    *,
    holds: str,
    wipe: Optional[Callable[[Path], bool]] = None,
    container: bool = True,
) -> Iterator[Scratch]:
    """A scratch directory and container name, both removed however the drill ends.

    A drill that passed but left its container or its restored data behind has
    not passed: the caller returns `ok and box.clean`. `holds` names what the
    directory holds, for the message that asks for it to be deleted by hand.
    `container=False` is for a drill that only restores files: it never starts
    one, so docker is not asked about it (and need not be installed).
    """
    box = Scratch(Path(tempfile.mkdtemp(prefix=f"{prefix}-")), f"{prefix}-{secrets.token_hex(4)}")
    try:
        yield box
    finally:
        # Unconditional: `docker run -d` can create the container and still fail.
        removed = not container
        try:
            if container:
                removed = remove_scratch_container(run, box.name)
        finally:
            wiped = (wipe or _rmtree)(box.workdir)
            if not wiped:
                logger.error(f"drill: could not remove {box.workdir}; it holds {holds}, delete it now")
            box.clean = removed and wiped
