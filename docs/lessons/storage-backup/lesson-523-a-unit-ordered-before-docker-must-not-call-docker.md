---
id: lesson-523-a-unit-ordered-before-docker-must-not-call-docker
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, systemd, docker, rpi4]
---

# A unit ordered `Before=docker.service` that calls the docker CLI deadlocks the boot until its own timeout

**Context**: On on-demand nodes, `node-backup-capture.service` is ordered
`Before=docker.service`, so it copies a quiet database before
`restart: unless-stopped` brings the writer back. On rpi4, the script found
its Pi-hole source with `docker volume inspect coredns_pihole_data`.

**Problem**: `docker.socket` is already listening at that point in the boot,
so the CLI connects. The connection asks systemd to start `docker.service`,
and that start job is queued behind the capture, which is waiting for the
answer. Nothing breaks the cycle except `TimeoutStartSec`. Measured
2026-10-07: the capture started at 02:42:09 and was killed at 02:47:09,
after its full 300s, and `docker.service` started in that same second. Pi-hole
and CoreDNS, the staging DNS gateway, were down for all of it. The same
failure on 2026-08-23, at the old 120s timeout, had been put down to IO
contention at boot, so the timeout was raised. Raising it only made the
outage longer. It looked intermittent because a capture started later, from
the hourly ship, finds Docker already up and finishes in a second.

**Solution**: The role now resolves the mountpoint with `docker volume
inspect` at apply time (`changed_when: false`, `check_mode: false`) and
renders it into the script as a literal. The script refuses to run if the
directory is gone. For a Docker volume that literal is safe: the path comes
from the volume's name and Docker's data-root, so it does not change when the
volume is recreated. A PVC path embeds the claim's UID, so that one is still
resolved at run time. After the change, a reboot of rpi4 ran the capture in
8s, and Docker started immediately after it. A test fails if any line of the
rendered capture script calls `docker`.

**Rule**: A unit ordered before a socket-activated service must not talk to
that service's socket. The call does not fail fast; it waits for the
service, which is waiting for the unit. If a boot-time unit times out once
and a later run of the same work takes a second, check the ordering for a
cycle before blaming load.

**Tags**: `#systemd` `#socket-activation` `#issue-1609`
