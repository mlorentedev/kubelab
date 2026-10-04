"""Reclaim the Docker residue a full disk leaves no other way to remove.

The Beelink runs two CI runners and Gitea on one Docker daemon. On
2026-09-05 its root filesystem reached 100% with 0 bytes free, which stopped
Gitea's SQLite from writing: the forge went down for writes -- no pushes, no
pull requests, no issues -- and act_runner spun on `pick task: database or disk
is full` every two seconds (#1657).

WHY THIS IS NOT `make maintain`. The weekly `node_maintenance` timer already
prunes images, build cache and stopped containers, and it RAN SUCCESSFULLY four
days before the disk filled. It could not have prevented this, for two reasons
that are both structural:

  1. `docker/setup-buildx-action` creates its buildkit container with
     `restart: unless-stopped`. The container therefore outlives the job, the
     runner, AND every reboot -- it is a permanent daemon resident, not
     residue. `docker container prune` removes STOPPED containers, so it can
     never reach one, and `docker builder prune` reads `~/.docker/buildx`
     rather than the host's containers (#1456). Measured: seven such state
     volumes holding 18.9GB, the largest 8.3GB.
  2. Ansible cannot run against a host with 0 bytes free -- it needs remote tmp
     for its own modules. The recovery path must therefore be lighter than the
     thing that was supposed to prevent it needing to exist.

AGE IS READ FROM `Created`, NEVER FROM UPTIME. `unless-stopped` restarts every
builder at boot, so `StartedAt` and `docker ps`'s "Up 3 hours" report the host's
uptime and not the container's. A builder created twenty hours ago reads as
three hours young minutes after a reboot, which is exactly backwards: the ones
that survived a reboot are the most certainly abandoned. This module compares
`Created`, and that difference is the whole safety argument for the age gate.

THE SAFETY PROPERTY IS DERIVED, NOT DECLARED. A volume is removed only when
every container attached to it is also being removed. That holds without anyone
maintaining a list of what to spare, which matters because the obvious list is
wrong in both directions: Gitea keeps its data in a BIND MOUNT under /opt, so
no volume operation can reach it at all, while `act-toolcache` and
`github_runner_toolcache` are volumes that must survive and would not appear on
a list written from memory. `docker volume prune` is never used here for the
same reason -- its blast radius is whatever happens not to be running at that
instant, which is a property of the moment rather than of the declaration.

DEFAULT IS A PLAN. Removing a builder that is genuinely mid-build fails that
job, so the command reports what it would do and changes nothing until told.

ONE FILTER, TWO CALLERS (OPS-024, 2026-10-04). The emergency path runs this from
the controller over SSH; the `node_maintenance` timer runs THIS SAME FILE on the
node (`main()` below; the role copies it to /opt), so the filter that decides what
an unattended timer deletes is the one these tests read. That is why the module
imports the standard library only: it has no toolkit to import on the node, and
`tests/test_node_maintenance_docker_reclaim.py` fails if it ever tries.

Every volume declared in `backup.sources` or ruled on in `backup.excluded` is
protected by name, derived from the declaration (`protected_volumes`) rather
than from a list kept here, and an empty derivation is refused: a reaper whose
protection silently came out empty is a `docker volume prune` with extra steps.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# `docker/setup-buildx-action`'s containers, and only those. The managed
# "multiarch" builder this fleet provisions deliberately is named
# `buildx_buildkit_multiarch0` and does NOT match -- the trailing `builder-` is
# what separates an action-generated instance from a declared one.
BUILDER_PREFIX = "buildx_buildkit_builder-"

# Volumes whose entire purpose is one CI job. Both are created by a runner and
# never read again once the job ends; neither is declared anywhere in this repo.
_RECLAIMABLE_VOLUME = re.compile(r"^(?:buildx_buildkit_builder-[0-9a-f-]+_state|GITEA-ACTIONS-TASK-\d+_.*)$")

# A builder older than the longest job this fleet runs cannot be mid-build.
# The slowest job measured here is `resume`'s LaTeX build against a 5.6GB
# TeX Live `SCHEME=full` image; four hours is roughly an order of magnitude
# above it, which is the margin an unattended timer needs and an operator
# watching the plan can lower with `--min-age-hours`.
DEFAULT_MIN_AGE_HOURS = 4

# Stopped while the reclaim runs, restarted afterwards. Freeing space is
# precisely the condition under which a queued job starts, and a job that
# starts mid-reclaim writes into the space just recovered while its builder is
# being removed underneath it.
RUNNER_CONTAINERS = ("act-runner", "github-runner")


def resolve_gate(min_age_hours: int | None) -> int:
    """`None` means "unset"; `0` means "reclaim everything", and they differ.

    This exists as a named function because the obvious spelling --
    `min_age_hours or DEFAULT_MIN_AGE_HOURS` -- silently maps 0 to the default,
    which makes the ONE value the emergency needs the one value that cannot be
    asked for. Make passes `MIN_AGE_HOURS=0` through as `--min-age-hours 0`
    quite happily, so the failure was invisible from both ends: the operator
    types the documented override and the tool ignores it without saying so.

    Tested through the CLI's own resolution rather than only through
    `plan_reclaim(min_age_hours=0)`, which passed throughout (lesson 433 --
    a path that is covered one layer below the defect is not covered).
    """
    if min_age_hours is None:
        return DEFAULT_MIN_AGE_HOURS
    return min_age_hours


class DockerUnavailableError(RuntimeError):
    """The daemon could not be asked. Distinct from 'there is nothing to do'."""


class ReclaimRefused(RuntimeError):
    """The situation is not the one this command is safe to act on."""


@dataclass(frozen=True)
class Container:
    name: str
    created: datetime
    running: bool
    volumes: tuple[str, ...]

    def age(self, now: datetime) -> timedelta:
        return now - self.created

    def label(self, now: datetime) -> str:
        hours = self.age(now).total_seconds() / 3600
        return f"{self.name} (created {hours:.1f}h ago, {'running' if self.running else 'stopped'})"


@dataclass(frozen=True)
class Volume:
    """A Docker volume, with what the plan needs to judge one nobody named.

    `created` is None only for a bare-name line (the 2026-09-05 transcription
    format); the live probe always reads `CreatedAt` and refuses a line it
    cannot parse. `anonymous` comes from the label Docker itself sets, never
    from the shape of the name: a 64-hex name is a convention, the label is a
    fact.
    """

    name: str
    created: datetime | None = None
    anonymous: bool = False


ANONYMOUS_LABEL = "com.docker.volume.anonymous"


@dataclass(frozen=True)
class ReclaimPlan:
    """What would be removed, and what matched but is being kept.

    `kept` is not decoration. A plan that lists only what it will do is
    indistinguishable from one that found nothing, and the difference between
    "no builders" and "six builders, all too young" is the difference between a
    clean node and an incident in progress.
    """

    containers: tuple[Container, ...] = ()
    volumes: tuple[str, ...] = ()
    kept_containers: tuple[tuple[Container, str], ...] = ()
    kept_volumes: tuple[tuple[str, str], ...] = ()

    @property
    def is_noop(self) -> bool:
        return not self.containers and not self.volumes


def parse_containers(payload: str) -> list[Container]:
    """`docker inspect -f '{{.Name}}|{{.Created}}|{{.State.Running}}|{{range .Mounts}}{{.Name}},{{end}}'`.

    `.Name` arrives with a leading slash and anonymous mounts have an empty
    `.Name`, so both are stripped here rather than in the caller -- an empty
    volume name that reached the plan would match nothing and be silently
    dropped, which is the quiet half of a bug whose loud half is removing the
    wrong thing.
    """
    containers: list[Container] = []
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("|")
        if len(parts) != 4:
            raise DockerUnavailableError(f"cannot parse container line: {line!r}")
        name, created, running, mounts = parts
        containers.append(
            Container(
                name=name.lstrip("/"),
                created=_parse_created(created),
                running=running.strip().lower() == "true",
                volumes=tuple(v for v in mounts.split(",") if v),
            )
        )
    return containers


def _parse_created(raw: str) -> datetime:
    """Docker emits RFC3339 with nanoseconds, which `fromisoformat` rejects
    before Python 3.11 and accepts inconsistently after. Truncate to
    microseconds and normalise the trailing Z, rather than trusting either."""
    text = raw.strip().replace("Z", "+00:00")
    if "." in text:
        head, _, tail = text.partition(".")
        match = re.match(r"^(\d+)(.*)$", tail)
        if match:
            fraction = match.group(1)[:6].ljust(6, "0")
            text = f"{head}.{fraction}{match.group(2)}"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise DockerUnavailableError(f"cannot parse container creation time {raw!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def parse_volumes(payload: str) -> list[Volume]:
    """`docker volume inspect -f '{{.Name}}|{{.CreatedAt}}|{{json .Labels}}'`.

    A bare name per line (`docker volume ls --format '{{.Name}}'`) is still
    accepted, as a volume of unknown age that is not known to be anonymous --
    which the plan treats exactly as #1665 did: a name pattern or nothing.
    """
    volumes: list[Volume] = []
    for line in payload.splitlines():
        line = line.strip()
        if not line:
            continue
        if "|" not in line:
            volumes.append(Volume(name=line))
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            raise DockerUnavailableError(f"cannot parse volume line: {line!r}")
        name, created, labels = parts
        try:
            label_map = json.loads(labels) or {}
        except ValueError as exc:
            raise DockerUnavailableError(f"cannot parse labels of volume {name!r}: {labels!r}") from exc
        volumes.append(Volume(name=name, created=_parse_created(created), anonymous=ANONYMOUS_LABEL in label_map))
    return volumes


def protected_volumes(backup: Mapping[str, Any]) -> frozenset[str]:
    """Every volume name `common.yaml`'s `backup` block declares, on any node.

    `backup.sources.<node>.<name>.volume` is backed up; every key under
    `backup.excluded.<node>` is a volume someone ruled on (a `pvc:` entry names
    a Kubernetes claim instead, and is skipped). All nodes, not just this one:
    a name declared anywhere is a name no reaper may take, and a per-node
    lookup is one more thing to get wrong.

    Refuses an empty result. The declaration names several volumes today, so
    nothing at all means the derivation broke (a missing file, a renamed key),
    and a reaper with no protection is the failure this function exists for.
    """
    names: set[str] = set()
    for node in (backup.get("sources") or {}).values():
        for source in (node or {}).values():
            if isinstance(source, Mapping) and source.get("volume"):
                names.add(str(source["volume"]))
    for node in (backup.get("excluded") or {}).values():
        for name, ruling in (node or {}).items():
            if not (isinstance(ruling, Mapping) and "pvc" in ruling):
                names.add(str(name))
    if not names:
        raise ReclaimRefused(
            "the backup declaration names no volume at all -- refusing to reclaim without "
            "knowing what to protect (is common.yaml's `backup` block where it was?)"
        )
    return frozenset(names)


def is_candidate(volume: Volume) -> bool:
    """CI residue by provenance: a runner's job volume, a builder's state, or a
    volume Docker created without a name. Anything else is never considered."""
    return bool(_RECLAIMABLE_VOLUME.match(volume.name)) or volume.anonymous


def plan_reclaim(
    containers: list[Container],
    volumes: Sequence[Volume],
    now: datetime,
    min_age_hours: int = DEFAULT_MIN_AGE_HOURS,
    *,
    protected: frozenset[str],
) -> ReclaimPlan:
    """Which builders are certainly abandoned, and which volumes follow them.

    A volume is removed only if it is CI residue by provenance (`is_candidate`),
    is not declared in the backup SSOT (`protected`), is held by no container
    that survives this plan -- stopped ones included -- and, when its creation
    time is known, is older than the gate. The attachment rule is what makes the
    command safe on a daemon it does not know the inventory of: it never needs
    to be told that `github_runner_toolcache` matters, because the container
    holding it says so. The name rule is what makes it safe when that container
    happens not to exist at this instant.
    """
    if min_age_hours < 0:
        raise ReclaimRefused(f"refusing a negative age gate ({min_age_hours}h)")
    if not protected:
        raise ReclaimRefused("refusing to plan with no protected volumes (see protected_volumes)")

    cutoff = timedelta(hours=min_age_hours)
    doomed: list[Container] = []
    kept_containers: list[tuple[Container, str]] = []

    for container in sorted(containers, key=lambda c: c.name):
        if not container.name.startswith(BUILDER_PREFIX):
            continue
        age = container.age(now)
        if age < cutoff:
            kept_containers.append(
                (
                    container,
                    f"created {age.total_seconds() / 3600:.1f}h ago, under the {min_age_hours}h gate "
                    "— it could still be mid-build",
                )
            )
            continue
        doomed.append(container)

    doomed_names = {c.name for c in doomed}
    # Every container's claim on every volume, including the ones we keep. Built
    # from the full container list rather than from the doomed set, because the
    # question a volume must answer is "does anything I am not removing still
    # hold this", and only the survivors can answer it.
    holders: dict[str, set[str]] = {}
    for container in containers:
        for mounted in container.volumes:
            holders.setdefault(mounted, set()).add(container.name)

    doomed_volumes: list[str] = []
    kept_volumes: list[tuple[str, str]] = []
    for volume in sorted(volumes, key=lambda v: v.name):
        if not is_candidate(volume):
            continue
        if volume.name in protected:
            kept_volumes.append((volume.name, "declared in common.yaml `backup` -- never reclaimed"))
            continue
        survivors = holders.get(volume.name, set()) - doomed_names
        if survivors:
            kept_volumes.append((volume.name, f"still held by {', '.join(sorted(survivors))}"))
            continue
        if volume.created is not None and volume.created > now - cutoff:
            hours = (now - volume.created).total_seconds() / 3600
            kept_volumes.append((volume.name, f"created {hours:.1f}h ago, under the {min_age_hours}h gate"))
            continue
        doomed_volumes.append(volume.name)

    return ReclaimPlan(
        containers=tuple(doomed),
        volumes=tuple(doomed_volumes),
        kept_containers=tuple(kept_containers),
        kept_volumes=tuple(kept_volumes),
    )


# `None` as the target means "this host": the node_maintenance timer runs the
# module on the node itself, with the same commands the emergency path sends.
LOCAL = None


def _ssh(ssh_target: str | None, command: str, timeout: int = 300) -> str:
    argv = (
        ["sh", "-c", command]
        if ssh_target is LOCAL
        else ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", ssh_target, command]
    )
    result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        raise DockerUnavailableError(f"{command} failed on {ssh_target or 'localhost'}: {result.stderr.strip()}")
    return result.stdout


def probe(ssh_target: str | None) -> tuple[list[Container], list[Volume]]:
    """One round trip each for volumes and containers, VOLUMES FIRST.

    The order closes a race. A job that starts between the two reads creates
    its volume and its container together, so with containers read first that
    volume would appear unheld. Read volumes first and any container created
    afterwards that mounts one is in the container read.

    `docker ps -aq` and `docker volume ls -q` can be empty, and `docker inspect`
    with no arguments exits non-zero, so both inspects are guarded remotely
    rather than here -- an empty daemon is a legitimate answer, not a failure.
    """
    raw_volumes = _ssh(
        ssh_target,
        'vols=$(docker volume ls -q); [ -z "$vols" ] || docker volume inspect '
        "-f '{{.Name}}|{{.CreatedAt}}|{{json .Labels}}' $vols",
    )
    raw_containers = _ssh(
        ssh_target,
        'ids=$(docker ps -aq); [ -z "$ids" ] || docker inspect '
        "-f '{{.Name}}|{{.Created}}|{{.State.Running}}|{{range .Mounts}}{{.Name}},{{end}}' $ids",
    )
    return parse_containers(raw_containers), parse_volumes(raw_volumes)


def disk_usage(ssh_target: str, mount: str = "/") -> str:
    """`df` on one line, for printing between steps.

    Read `Used`, not `Avail`: the filesystem reserves 5% for root, so `Avail`
    reports 0 to an unprivileged process while dockerd -- running as root --
    still has room to write. That reserve is why Gitea's SQLite failed while
    builders kept starting, and why `Avail` stays at 0 through the first part
    of a reclaim that is working.
    """
    return _ssh(ssh_target, f"df -h {mount} | tail -1").strip()


def _checked_name(name: str) -> str:
    """Names are interpolated into a remote shell command.

    They come from Docker's own output, so this asserts an invariant rather
    than sanitising input -- the day the parse loosens, this is the line that
    has to fail rather than the line that builds `docker rm -f $(anything)`.
    """
    if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$", name):
        raise ReclaimRefused(f"refusing to build a remote command around {name!r}")
    return name


def set_runners(ssh_target: str, running: bool, containers: tuple[str, ...] = RUNNER_CONTAINERS) -> list[str]:
    """Stop or start the runners, tolerating ones this node does not have.

    Returns the containers it actually acted on. `|| true` per container rather
    than for the whole command: a node without `github-runner` must not mask a
    failure to stop `act-runner`, which is the one that would keep filling the
    disk.
    """
    verb = "start" if running else "stop"
    acted: list[str] = []
    for name in containers:
        checked = _checked_name(name)
        output = _ssh(
            ssh_target,
            f"docker inspect {checked} >/dev/null 2>&1 && docker {verb} {checked} || echo ABSENT",
        )
        if "ABSENT" not in output:
            acted.append(name)
    return acted


def remove(ssh_target: str | None, plan: ReclaimPlan) -> None:
    """Containers first, then volumes. The order is not interchangeable:
    Docker refuses to remove a volume that is still attached, so a volume pass
    before the container pass fails on every volume that matters."""
    for container in plan.containers:
        _ssh(ssh_target, f"docker rm -f {_checked_name(container.name)}")
    for volume in plan.volumes:
        _ssh(ssh_target, f"docker volume rm {_checked_name(volume)}")


def prune_images(ssh_target: str, include_tagged: bool = False) -> str:
    """Dangling images by default.

    `-a` additionally evicts tagged-but-unused images, which on this node means
    `runner-images:ubuntu-latest` and the GH runner image -- a pull-time cost,
    not data. The weekly `node_maintenance` timer already runs `-af` here, so
    `-a` is within established practice on this host rather than an escalation;
    it is off by default only because the `df` between steps should decide it.
    """
    flag = "-af" if include_tagged else "-f"
    return _ssh(ssh_target, f"docker image prune {flag}", timeout=600).strip()


def main(argv: list[str] | None = None) -> int:
    """The `node_maintenance` timer's entry point, run on the node itself.

    No runner pause and no image prune here: the age gate is what protects a
    live build on an unattended run, and the maintenance script prunes images
    after this returns. Exits non-zero on anything it could not do, so the
    script records a failure and the unit's `OnFailure=` tells someone.
    """
    parser = argparse.ArgumentParser(description="Reclaim orphaned buildx builders and CI job volumes on this host.")
    parser.add_argument("--declaration", required=True, type=Path, help="JSON of common.yaml's `backup` block")
    parser.add_argument("--min-age-hours", type=int, default=DEFAULT_MIN_AGE_HOURS)
    parser.add_argument("--apply", action="store_true", help="remove; default reports only")
    args = parser.parse_args(argv)

    now = datetime.now(timezone.utc)
    try:
        protected = protected_volumes(json.loads(args.declaration.read_text(encoding="utf-8")))
        containers, volumes = probe(LOCAL)
        plan = plan_reclaim(containers, volumes, now, args.min_age_hours, protected=protected)
        for container in plan.containers:
            print(f"remove container  {container.label(now)}")
        for name in plan.volumes:
            print(f"remove volume     {name}")
        for container, why in plan.kept_containers:
            print(f"keep container    {container.name} -- {why}")
        for name, why in plan.kept_volumes:
            print(f"keep volume       {name} -- {why}")
        if args.apply:
            remove(LOCAL, plan)
    except (DockerUnavailableError, ReclaimRefused, OSError, ValueError) as exc:
        print(f"docker reclaim FAILED: {exc}", file=sys.stderr)
        return 1
    verb = "reclaimed" if args.apply else "would reclaim"
    print(f"{verb} {len(plan.containers)} container(s), {len(plan.volumes)} volume(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
