---
id: lesson-656-an-unfinished-boot-is-judged-by-its-jobs-own-timeouts-because-a-randomized-catch-up-makes-any-clock-bound-false
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: observability
tags: [kubelab, observability, systemd, lab-edge]
---

# An unfinished boot is judged by its jobs' own timeouts, because a randomized catch-up makes any clock bound false

**Context**: #2776 asked the edge's boot check to read `systemctl is-system-running`
past `starting`. The first design was a fixed limit: past N minutes since boot, a
boot still starting fails. N would be derived from the units the roles ship, such as
`node-backup-ship` (`OnBootSec=2min`, then `TimeoutStartSec=600`).

**Problem**: A boot finishes once systemd's job table first empties (lesson-653),
and any timer that fires while it is still running adds a job to it. A
`Persistent=true` timer that missed a run fires at boot, and its
`RandomizedDelaySec` applies to that catch-up too: `kubelab-maintenance.timer` can
join anywhere in the first hour (`RandomizedDelaySec=3600`), then hold 10 minutes.
So a limit that covers every shipped unit is over an hour, too long to tell anyone
anything after a power cut, and a shorter one is not a bound. The clock cannot
separate a slow boot from a stuck one.

**Solution**: Judge the jobs. `systemctl list-jobs` names each running start job,
and `systemctl show -p TimeoutStartUSec --value <unit>` gives the timeout that ends
it, as systemd prints it (`10min`). A job with a timeout will end by itself, so the
check reads `WAIT` and names each with its timeout. `infinity` is a oneshot's
default, and nothing ends that job, so the check fails and names the unit. Read on
the edge, systemd 255: the hand-made `tailscale-watchdog.service` and
`kubelab-edge-lease-check.service` print `infinity`, `node-backup-ship.service`
prints `10min`. A waiting job has not started, and a target or a device has no
start timeout, so neither is judged. `degraded` is a finished boot with failed
units.

**Rule**: When a deadline depends on events that can arrive late at random, check
whether each pending thing has its own end, rather than measuring the time
elapsed.

**Tags**: `#systemd` `#boot` `#lab-edge` `#issue-2776`
