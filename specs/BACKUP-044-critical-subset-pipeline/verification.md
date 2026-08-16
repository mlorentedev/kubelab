---
tags: [spec, verification]
created: "2026-08-15"
---

# Verification - BACKUP-044-critical-subset-pipeline

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test
name, or observed behavior).

- [ ] AC1 (every Tier 1/2 item present in its node's R2 repo, listed from a non-source machine) -> not started
- [ ] AC2 (all four SQLite DBs snapshotted with `sqlite3 .backup`, proven by restoring one) -> not started
- [ ] AC3 (restore exercised end-to-end for Gitea + one always-on consumer) -> not started
- [ ] AC4 (failed backup alerts on the #686 path; a missed window on a powered-off node does not) -> not started
- [ ] AC5 (on-demand trigger model exercised across a real power cycle) -> design settled below (R-C), not built
- [ ] AC6 (sources enumerated from an SSOT allow-list) -> substrate finding below, not built
- [ ] AC7 (`restic check` passes on every repository as part of the run) -> feasibility settled below (R-B), not built
- [ ] AC8 (no new consumer of `minio:9000`) -> not started

## Open questions, settled

Part 0 of `tasks.md`. The three risks `proposal.md` named as gating are settled here, each
by measurement on the live device rather than by reading configuration. Fleet reached over
Tailscale; the homelab was powered on for the whole session (`tailscale status`: rpi3, rpi4,
beelink, ace1, ace2, vps online; `aws1` offline ~1h, unrelated and flagged separately).

Every command in R-C and in the collateral findings is read-only. R-B installs a throwaway
static binary under `/var/tmp` and removes it; no package state on the RPi3 changed, verified
at the end of each run (`restic absent from PATH: yes`).

---

### R-C — can a boot snapshot be ordered before Gitea's first write?

**Settled 2026-08-15. Yes, but the ordering target in the proposal would not have worked.**
The correct constraint is `Before=docker.service`, not `Before=kubelab-compose.service`.

`proposal.md` framed this as a doubt about `Persistent=true`. That framing is right to be
suspicious and wrong about the mechanism: the question is not whether a timer is ordered, it
is **what actually starts the writer**. Measured on the Beelink's current boot:

| t (from boot) | event | source |
|---|---|---|
| 0s | boot | `uptime -s` -> `2026-08-16 01:44:40` |
| +10s | `docker.service` starts | `ExecMainStartTimestamp=01:44:50`, monotonic `9543372` |
| +33s | `kubelab-compose.service` runs `ExecStart` | `ExecMainStartTimestamp=01:45:13`, monotonic `32122198` |
| +33.5s | **gitea container starts** | `docker inspect .State.StartedAt` -> `2026-08-15T23:45:13.53Z` (= 01:45:13.53 CEST) |

Gitea starts **with the compose unit**, not with dockerd 23 seconds earlier — even though
every container carries `restart: unless-stopped` and dockerd was up the whole time:

```
minio          restart=unless-stopped
gitea          restart=unless-stopped
github-runner  restart=unless-stopped
```

The reason is the semantics of `unless-stopped` specifically: `kubelab-compose.service`
carries `ExecStop=/usr/bin/docker compose -f .../compose.yml stop`, which marks the
containers as explicitly stopped, and `unless-stopped` means exactly "do not resurrect
something that was stopped on purpose". That is the whole difference from `always`.

**So the ordering handle exists — but only on the clean-shutdown path.** On a power cut
`ExecStop` never runs, the containers were `running` when dockerd died, and `unless-stopped`
*will* auto-start Gitea at the `docker.service` mark. On this node that is not an edge case:
the Beelink is `location: on-demand` (ADR-028 / ADR-061), and `kubelab-compose.service`'s own
header says powering it on **is** its normal operation. Anything ordered against the compose
unit is 23 seconds too late in precisely the scenario the design must survive.

**Design consequence for `tasks.md`:** order the capture unit `Before=docker.service`. That
dominates both paths and needs no reasoning about whether the last shutdown was clean. It has
a second, larger benefit: with dockerd down there is no writer at all, so the snapshot is
taken against a quiescent database rather than a live one.

This splits the unit in two, and the split should be explicit in the design:

- **capture** — `Before=docker.service`, local disk only, `sqlite3 .backup` into a staging
  dir. Must be ordered; must be fast, because it delays every boot.
- **ship** — restic to R2. Needs the network, must *not* be ordered before dockerd, and its
  latency must never sit on the boot path.

Ordering an R2 upload before `docker.service` would put a network round-trip in front of
Gitea starting on every power-on. Capture is the only half that needs the ordering guarantee.

`ExecStop` on the compose unit also gives the graceful-shutdown snapshot the proposal asks
for, with a caveat to settle at implementation: systemd stops units in reverse dependency
order, so a capture unit ordered `After=` the compose unit stops *first* — while Gitea is
still running, which is a live-database snapshot and needs `sqlite3 .backup` rather than a
file copy.

Gitea's database was not written this boot (`/opt/gitea/data/gitea/gitea.db`, 2,113,536 bytes,
mtime `2026-08-14 07:13`, node up 8 min at the time of measurement), consistent with the forge
still being empty pending #1076.

---

### R-B — does restic fit in the RPi3's 1GB?

**Settled 2026-08-15, and it splits into two answers.** Feasibility is proven. The memory
cap the design wanted to run it under is *unobtainable on this node today*, for a verified
reason, and that converts into a prerequisite task rather than a number.

**Feasibility: yes, measured on the device.** restic 0.18.1 (static arm64 binary, scratch
only) against the live Uptime Kuma volume, with Uptime Kuma running throughout:

```
backup #1 (cold)   processed 5 files, 21.642 MiB in 0:03   -> 4.831 MiB stored
backup #2 (warm)   processed 5 files, 21.642 MiB in 0:00   -> 294.217 KiB stored (dedup hit)
check              2 / 2 snapshots, no errors were found
```

Then a deliberately oversized probe, because restic's index scales with *repository* size and
not with one snapshot — the proposal's actual concern:

```
backup #3   processed 24668 files, 904.873 MiB in 2:35  -> repo grew to 399M
check       3 / 3 snapshots, no errors were found
```

A ~40x oversized workload completed on a 906MB node without an OOM and without disturbing the
service. The real steady-state workload is a 22MB payload in a ~6MB repository. Feasibility is
not in doubt, and the fallback the proposal held in reserve (stream the snapshot to a node that
can run restic) is **not needed** — that risk is closed.

**The deployable cap: blocked, root cause verified.** Two attempts to obtain a number failed
before the reason became clear, and the failures are recorded because the second one nearly
shipped a false result:

1. `/usr/bin/time -v` is not installed on the RPi3 — no output, no numbers.
2. Reading `memory.peak` from the scope's own cgroup returned nothing.
3. Falling back to "let the kernel be the oracle" — run under a descending `MemoryMax` with
   `MemorySwapMax=0` and see where it dies — reported **survival all the way down to 16M**.

That third result is implausible on its face; a Go runtime alone exceeds 16MB RSS. The control
experiment settles it:

```
$ cat /sys/fs/cgroup/cgroup.controllers
cpuset cpu io pids                                   # <- no `memory`

$ sudo systemd-run --scope -p MemoryMax=64M -p MemorySwapMax=0 \
    python3 -c "b = bytearray(300*1024*1024); ...touch every page..."
ALLOCATED 300MB AND SURVIVED
control exit=0

# inside a live scope:
memory.max=cat: /sys/fs/cgroup/system.slice/run-....scope/memory.max: No such file or directory
```

Docker agrees, in its own words:

```
$ docker info
WARNING: No memory limit support
WARNING: No swap limit support
```

**The memory cgroup controller does not exist on the RPi3.** Every `MemoryMax` in the sweep was
a silent no-op, so takes 2 and 3 measured nothing and none of their numbers are results. The
only valid artifacts from them are the control experiment above and the uncapped existence
proof quoted under "Feasibility".

**This is drift on one node, not a Raspberry Pi property.** Checked across the fleet:

| node | `cgroup.controllers` | memory |
|---|---|---|
| rpi3 | `cpuset cpu io pids` | **ABSENT** |
| rpi4 | `cpuset cpu io memory hugetlb pids rdma misc` | present |
| beelink | `cpuset cpu io memory hugetlb pids rdma misc` | present |
| ace1 | `cpuset cpu io memory hugetlb pids rdma misc` | present |

The RPi4 is also a Raspberry Pi and has the controller, so the cause is not the hardware. It is
the OS, visible in each node's `cmdline.txt`: the RPi4 boots `root=LABEL=writable` with
`fixrtc` (Ubuntu Server for Pi, whose kernel enables the memory cgroup by default), while the
RPi3 boots `root=PARTUUID=bdb42b29-02` on kernel `6.12.47+rpt-rpi-v8` — the `rpt` marks the
Raspberry Pi Foundation kernel, which ships the memory cgroup disabled to save memory. Neither
node passes `cgroup_enable=memory` explicitly; the RPi4 does not need to.

**Design consequence:** do not drop the cap from the design. `MemorySwapMax=0` is a no-op today
too, the node has ~900MB of swap and was observed using it (128MB -> 218MB across the runs), and
an unbounded restic on the monitoring of record for prod is exactly what the cap exists to
prevent. The cap becomes an ordered prerequisite: enable the controller -> re-measure with a
real oracle -> deploy with a cap chosen from that measurement.

**This is not a latent gap — a declared control is already being discarded.** An earlier draft
of this section claimed nothing on the RPi3 relies on a limit that silently fails. That was
wrong. `common.yaml:736-740` declares `memory_limit: 256M` for Glances, the `glances` role
renders it, and it is present in the rendered file on the node:

```
$ sudo grep -A6 "resources:" /opt/glances/compose.yml
      resources:
        limits:
          cpus: "0.25"
          memory: "256M"
```

What the kernel actually granted:

```
glances        HostConfig.Memory=0  NanoCpus=250000000
uptime-kuma    HostConfig.Memory=0  NanoCpus=0
```

The **CPU limit from that same block was applied** (`NanoCpus=250000000` = 0.25 CPU) and the
memory limit was dropped. Same block, same `docker compose` run, same Compose v5.4.0 — which
rules out swarm-key semantics, Compose version and template drift, and leaves only the
controller list: `cpu` is present in `cgroup.controllers`, `memory` is not.

That asymmetry is also why this went unnoticed. The adjacent control in the same stanza works,
so any spot check that happened to look at CPU would confirm "limits are applied". An
SSOT-declared resource control is being silently discarded on the monitoring of record for
prod, today — and the same silence would swallow the cap this spec wants for restic.

---

### R-A — where does the restic repository password live?

**Settled 2026-08-15 by the operator: independent escrow in Bitwarden, not SOPS.**

The circularity `proposal.md` names is real: a repository password stored only in
`common.enc.yaml` is decrypted by an age key that lives on a laptop and an encrypted USB in one
physical location — the same location a disaster destroys. Backups in R2 would survive and be
unrecoverable.

Bitwarden is already the fleet's secret manager (`dotf secrets`), and it is hosted, so it is
independent of both the age key and the site. Recovering from total loss therefore needs
Bitwarden plus the R2 credentials, and no artifact from the destroyed location.

Implementation notes for `tasks.md`:

- The password is **not** registered in `SECRET_CATALOG` as the recovery copy. R2's *access*
  credentials still belong in SOPS (they are operational, rotatable and not recovery-critical
  in the same way); the repository password is the one artifact that must not depend on age.
- The runbook must state which artifact lives where, or the split becomes its own failure mode.
- Coordinate the vault item with the dotfiles lane: its folder taxonomy changed in
  dotfiles#982, and `dotf secrets run` without `--only` is currently broken (dotfiles#985).
- #479 keeps its verification exercise regardless — decrypt a SOPS file using only the USB
  copy, on a machine that is not the laptop. This decision removes the *backup* leg from that
  dependency; it does not remove the dependency.

---

## Collateral findings

Three things turned up while settling the above that change the design's substrate.

### The allow-list must enumerate paths, not Docker volumes (#1092 AC3)

On the Beelink, the two things that matter are **bind mounts, not volumes**:

```
gitea   bind  src=/opt/gitea/data  -> /data
minio   bind  src=/opt/minio/data  -> /data
```

`docker volume ls` on that node returns only buildx builder state and the runner's
`github_runner_data` / `github_runner_toolcache`. The existing `backup` role does support
explicit paths (`backup_filesystem_paths`), so the role is not incapable — the defect is the
**discovery axis**: `roles/backup/tasks/main.yml` enumerates `docker volume ls` and subtracts
`backup_exclude_volumes`. Pointed at the Beelink as configured, that model would archive
rebuildable build caches and miss Gitea and MinIO entirely, while reporting success.

Compounding it, `common.yaml` defines a `backup` block for the VPS only, so the Beelink has no
coverage at all today regardless of model. This is the concrete argument for #1092's AC3 and
for making the allow-list path-based from the start.

### #1092 instance 1 is resolved — the live Uptime Kuma volume is `uptime_kuma_data`

Three independent signals agree, which matters because the orphan is the *larger* of the two
and carries the more canonical-looking name:

| volume | size | newest mtime | mounted by the running container |
|---|---|---|---|
| `uptime_kuma_data` | 22M | `2026-08-16 01:53` (live) | **yes** -> `/app/data` |
| `uptime-kuma_uptime_kuma_data` | 26M | `2026-03-28 04:32` (frozen) | no |

`docker inspect uptime-kuma` reports `volume uptime_kuma_data -> /app/data`. The allow-list
must name `uptime_kuma_data` explicitly. A backup written against the orphan would capture 26M
of healthy-looking data the service does not read and would pass any check asserting only that
a non-empty backup exists.

### Payload size correction

`proposal.md` states the Uptime Kuma payload is 18M. Measured 2026-08-15 it is **22M**
(`21.642 MiB` as restic accounts it). Not material to any decision; recorded so the number is
not re-derived from the stale one.
