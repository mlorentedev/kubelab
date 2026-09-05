---
id: lesson-437-a-restart-policy-makes-container-uptime-measure-the-host
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: containers-docker
tags: [kubelab, containers-docker, docker, buildx, ci, verification, ops-024]
---

# A restart policy makes container uptime measure the host, not the container

> Number: 430 and 431 are claimed by #1648, 432 by a parallel session, and 434,
> 435 and 436 by open PR #1662. Taken as 437 after checking all of them, because
> announcing a number is not allocating one (#1334).

**Date:** 2026-09-05
**Context:** OPS-024 / #1657 — the Beelink root filesystem reached 0 bytes free
**Category:** containers-docker

## What happened

The Beelink's root filesystem hit 100% with 0 bytes available. Gitea's SQLite
could not write, so the forge went down for writes, and act_runner spun on
`pick task: database or disk is full` every two seconds.

`docker ps` showed six `buildx_buildkit_builder-*` containers. Every one of
them read **Up 3 hours** — consistent with the host's uptime, and consistent
with the story everyone had: `personal/resume` migrated to this forge two days
earlier and its CI ran here for the first time the day before.

`docker inspect` told a different story — one #1456 had already written down a
week earlier, and which nobody had connected to disk:

| builder | `Created` | age | `docker ps` |
|---|---|---|---|
| `42d82788` | 2026-05-24 | 104 days | Up 3 hours |
| `6598ae36` | 2026-06-18 | 79 days | Up 3 hours |
| `bfbd55c5` | 2026-06-20 | 77 days | Up 3 hours |
| `3785131b` | 2026-06-26 | 71 days | Up 3 hours |

`docker/setup-buildx-action` creates its buildkit container with
`restart: unless-stopped`. The container therefore outlives the job, outlives
the runner, and is **restarted by the daemon at every boot**. `StartedAt` — and
so the `Up …` column, which is derived from it — resets each time. Four
builders had been resident since May, from the *GitHub* runner, months before
the Gitea forge existed on that node. `resume`'s 5.6GB images were the last
straw, not the mechanism.

## The general shape

**A duration resets on an event that has nothing to do with what you are
measuring.** Container uptime answers "how long since this process last
started", and a restart policy makes the answer a property of the *host's* last
reboot. Ask it "how long has this been lying around" and it answers a different
question in the same units, which is what makes it convincing.

The direction of the error is what makes it expensive: the containers that have
survived the most reboots are the most certainly abandoned, and they are exactly
the ones uptime reports as youngest. The signal is not merely uninformative —
it is anti-correlated with the thing you want.

This is the family that keeps recurring here — a signal that answers a weaker or
different question than the one asked ([[lesson-425]], [[lesson-428]]) — but the
mechanism is concrete enough to state on its own, and it is not confined to
buildx: any container with `restart: always` or `unless-stopped` has the same
property.

## Why nothing caught it

The node runs a weekly `node_maintenance` timer that prunes images, build cache
and stopped containers. It ran successfully on 2026-09-01 and could never have
removed any of these:

- `docker container prune` removes **stopped** containers. `unless-stopped`
  means one is never stopped.
- `docker builder prune` reads `~/.docker/buildx/instances` — the client's
  view — not the host's containers, so it does not see them either.
- `docker system df` under-reports the cost: a *running* container's volume is
  not counted as reclaimable. The seven state volumes held 18.9GB, the largest
  8.3GB, none of it in the "reclaimable" figure.

#1456 had already found these containers on 2026-08-27 and chose to **report**
rather than remove them, in its own words because "the timer cannot distinguish
an orphan from a build genuinely in progress". That was the right call: without
a durable age, "is this mid-build?" has no safe answer, and killing a live
builder fails someone's job.

**And #1456 had already read the dates correctly** — it records the same four
builders, "created 2026-05-24 through 2026-06-26". The ages were not hidden from
it. What it concluded was that the impact was "cosmetic (25-35MB RAM each, no
CPU)", with the growth risk framed as *RAM*. Their state volumes — 18.9GB, the
largest 8.3GB — were never in the frame, because `docker system df` does not
count a running container's volume as reclaimable.

That is the second time in this incident that a correct measurement of this node
answered a narrower question than the one that mattered: #1652/lesson-431 sized
the same node under CI load and also concluded the constraint was memory. Two
tickets, both accurate, both scoped to RAM, while the disk filled. **The failure
was not measurement — it was the frame**, and a frame is not visible from inside
itself. What would have surfaced it is an alert on the resource nobody was
looking at, which is why "add a disk alert" outranks "look harder" as a fix.

## What to do instead

**Read `Created`, never uptime, whenever the question is "how long has this been
here".** It is set once and survives restarts, which is precisely the property
uptime lacks.

```bash
docker inspect -f '{{.Name}} {{.Created}} {{.State.Running}}' $(docker ps -aq)
```

With a durable age, the report-only stance becomes actionable: a builder older
than the longest job the fleet runs cannot be mid-build, so an age gate turns an
unanswerable question into an arithmetic one. `toolkit/features/docker_reclaim.py`
implements that, and its module docstring states the reasoning at the place
someone changing it will read.

## How to notice it without an incident

- **A cluster of identical uptimes is a reboot, not a workload.** Six containers
  all reading "Up 3 hours" is one event, not six.
- **`docker ps` and `docker inspect` disagreeing about age is not a display
  quirk.** If they differ, a restart policy is in play and only one of them is
  answering your question.
- A disk alert would have fired in July. The first signal here was a `500` from
  an unrelated command — which is to say, no signal at all.

## Corollary: why "remove by name, never `docker volume prune`"

The standing advice was right and its stated reason was wrong. It was "MinIO and
Gitea live on the same daemon" — but both keep their data in **bind mounts**
under `/opt`, which no volume operation can reach. Measured, not assumed.

The real reason survives the correction and is stronger: `prune`'s blast radius
is whatever happens not to be running at that instant, which is a property of
the moment rather than of the declaration. `act-toolcache` and
`github_runner_toolcache` are volumes that genuinely must survive, and they
would not have appeared on a spare-list written from memory. So the reclaim
derives protection from live attachments — a volume is removed only when every
container holding it is also being removed — instead of consulting a list that
was wrong in both directions.

## Related

- [[lesson-433]] — a branch that only improves a message is invisible to a test
  that asserts only failure. Same PR; the mutation run that found it also found
  this module's untested removal order.
- [[lesson-425]] — a probe that measures a single target measures that target's
  history.
- [[lesson-428]] — a sample is not the population; state the frame next to the
  verdict.
