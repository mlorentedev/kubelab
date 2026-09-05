"""Reclaim the Docker residue a full disk leaves no other way to remove.

The Beelink runs two CI runners, Gitea, and MinIO on one Docker daemon. On
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
wrong in both directions: Gitea and MinIO keep their data in BIND MOUNTS under
/opt, so no volume operation can reach them at all, while `act-toolcache` and
`github_runner_toolcache` are volumes that must survive and would not appear on
a list written from memory. `docker volume prune` is never used here for the
same reason -- its blast radius is whatever happens not to be running at that
instant, which is a property of the moment rather than of the declaration.

DEFAULT IS A PLAN. Removing a builder that is genuinely mid-build fails that
job, so the command reports what it would do and changes nothing until told.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

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


def parse_volumes(payload: str) -> list[str]:
    """`docker volume ls --format '{{.Name}}'`."""
    return [line.strip() for line in payload.splitlines() if line.strip()]


def plan_reclaim(
    containers: list[Container],
    volumes: list[str],
    now: datetime,
    min_age_hours: int = DEFAULT_MIN_AGE_HOURS,
) -> ReclaimPlan:
    """Which builders are certainly abandoned, and which volumes follow them.

    A volume is removed only if EVERY container holding it is also being
    removed. That derivation is what makes the command safe on a daemon it does
    not know the inventory of -- it never needs to be told that
    `github_runner_toolcache` matters, because the running container holding it
    says so.
    """
    if min_age_hours < 0:
        raise ReclaimRefused(f"refusing a negative age gate ({min_age_hours}h)")

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
        for volume in container.volumes:
            holders.setdefault(volume, set()).add(container.name)

    doomed_volumes: list[str] = []
    kept_volumes: list[tuple[str, str]] = []
    for volume in sorted(volumes):
        if not _RECLAIMABLE_VOLUME.match(volume):
            continue
        survivors = holders.get(volume, set()) - doomed_names
        if survivors:
            kept_volumes.append((volume, f"still held by {', '.join(sorted(survivors))}"))
            continue
        doomed_volumes.append(volume)

    return ReclaimPlan(
        containers=tuple(doomed),
        volumes=tuple(doomed_volumes),
        kept_containers=tuple(kept_containers),
        kept_volumes=tuple(kept_volumes),
    )


def _ssh(ssh_target: str, command: str, timeout: int = 300) -> str:
    result = subprocess.run(
        ["ssh", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes", ssh_target, command],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise DockerUnavailableError(f"{command} failed on {ssh_target}: {result.stderr.strip()}")
    return result.stdout


def probe(ssh_target: str) -> tuple[list[Container], list[str]]:
    """One round trip each for containers and volumes.

    `docker ps -aq` can be empty, and `docker inspect` with no arguments exits
    non-zero, so the inspect is guarded remotely rather than here -- an empty
    daemon is a legitimate answer, not a failure.
    """
    raw_containers = _ssh(
        ssh_target,
        'ids=$(docker ps -aq); [ -z "$ids" ] || docker inspect '
        "-f '{{.Name}}|{{.Created}}|{{.State.Running}}|{{range .Mounts}}{{.Name}},{{end}}' $ids",
    )
    raw_volumes = _ssh(ssh_target, "docker volume ls --format '{{.Name}}'")
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


def remove(ssh_target: str, plan: ReclaimPlan) -> None:
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
