---
tags: [spec, verification]
created: "2026-08-15"
---

# Verification - BACKUP-044-critical-subset-pipeline

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test
name, or observed behavior).

- [ ] AC1 (every node-path consumer present in its node's R2 repo, listed from a non-source machine) -> re-scoped below, not started
- [ ] AC2 (all four SQLite DBs snapshotted with `sqlite3 .backup`, proven by restoring one) -> not started
- [ ] AC3 (restore exercised end-to-end for Gitea + one always-on consumer) -> not started
- [ ] AC4 (failed backup alerts on the #686 path; a missed window on a powered-off node does not) -> not started
- [ ] AC5 (on-demand trigger model exercised across a real power cycle) -> design settled below (R-C), not built
- [ ] AC6 (sources enumerated from an SSOT allow-list) -> substrate finding below, not built
- [ ] AC7 (`restic check` passes on every repository as part of the run) -> feasibility settled below (R-B), not built
- [ ] AC8 (no new consumer of `minio:9000`) -> not started
- [ ] AC9 (a node past its backup window alerts unprompted) -> not started

### 2026-08-22 — the PVC class joins, and the first real restore

**Authelia and n8n now have a copy outside the cluster they run in.** Until today
their only backup was the prod `pvc-backup` CronJob writing to MinIO *inside the
same cluster* — a copy that burns with the thing it protects — via an `mc`
binary downloaded unpinned from the public internet on every run.

Deployed to all four nodes and exercised on the VPS:

```
kubelab-vps : ok=28 changed=2 unreachable=0 failed=0
kubelab-vps: backup complete (Result=success, ExecMainStatus=0)
  ship complete: s3:.../kubelab-backups/kubelab-vps
  coverage heartbeat posted
```

Contents of the resulting snapshot, listed from the workstation:

```
/opt/node-backup/staging/authelia/db.sqlite3       462848
/opt/node-backup/staging/headscale/db.sqlite       118784
/opt/node-backup/staging/n8n/database.sqlite       946176
```

**The number that proves the mechanism is 946176.** The live file is 892 KB;
the snapshot holds 946 KB, because `sqlite3 .backup` folded in the 4.1 MB WAL
measured on that database earlier the same day. A plain file copy would have
stored the smaller, older file — and it would have restored *cleanly*, as a
database missing most of its recent history. That is the failure this mechanism
exists to prevent, and this is the first time the difference has been visible in
a real artifact rather than argued from the manual.

**AC2 closed, on the restored copy rather than on exit codes.** Restored from R2
into a scratch directory on the workstation — never over the live data, which is
the thing the backup exists to protect:

```
n8n/database.sqlite     integrity=ok   63 tables   credentials_entity: 1 row
authelia/db.sqlite3     integrity=ok   26 tables
```

The scratch copy was deleted afterwards.

**The PVC path resolver was the risk, and it held.** `local-path` embeds the
claim UID in the directory name, so the path is resolved on the node at capture
time via `kubectl get pv`, filtered on namespace *and* claim. Verified against
the live cluster before deploying, and then implicitly by the capture succeeding
— had it resolved to nothing, the run would have refused loudly rather than
staging an empty directory.

**A misreading corrected in passing.** `make backup-coverage` reports `1 path(s)`
for the VPS both before and after. That field is restic's *backup argument*
count — always the one staging directory — not the number of sources. It is not
a coverage signal, and reading it as one would have hidden exactly this change.

**Still not retired: the CronJob and MinIO (#972).** Deliberate ordering — they
keep running until these snapshots have been verified in R2, which they now
have, so that retirement is next rather than pending.
### 2026-08-22 — AC4's failure injection, three ways

Run against **beelink** with the homelab powered on, from least to most
invasive, so each result bounds what the next can claim. Healthy baseline first:
`beelink: backup complete (Result=success, ExecMainStatus=0)`.

**1. Synthetic unit** — `ExecStart=/bin/false` carrying the same
`OnFailure=kubelab-notify@%n.service`. The notifier ran as
`kubelab-notify@backup-ac4-probe.service.service` with `Result=success`,
`ExecMainStatus=0`. Since the script's curl uses `-f`, that is n8n answering
2xx. Proves the linkage and `%n` -> `%i` expansion on real hardware. Does NOT
prove a failing backup triggers it — which is exactly why AC4 says "inject a
failure, not review configuration", and why this was only the first step.

**2. R2 blackholed** via `/etc/hosts` on the node, no credential touched.
`Result=timeout`, `ExecMainStatus=15`, notifier fired with a real
`InvocationID`. `/etc/hosts` restored afterwards.

**3. Invalid R2 credential** — the secret file replaced with 30 bytes of
garbage, original saved and restored. Same verdict: `Result=timeout`,
`ExecMainStatus=15`, notifier fired.

**AC4's first half is closed**: a genuinely failed backup raises the envelope,
demonstrated twice by two independent causes, not by reading the manifest.

#### The finding: every failure looks like a timeout

Both real injections settled as `Result=timeout` after **~180-195 seconds**, and
the journal carried **no restic error at all** — no "denied", no "invalid", no
"signature". A wrong credential and an unreachable endpoint are indistinguishable
from the outside, and both are indistinguishable from a slow network.

Two consequences worth stating rather than discovering later:

- The operator receives "node-backup-ship.service failed on beelink" with a
  journal tail that ends mid-run and explains nothing. The envelope is correct
  and nearly useless for diagnosis.
- 180s is not `TimeoutStartSec=600`. Something inside restic or the AWS SDK is
  imposing its own retry budget, and the unit's own ceiling never applies. That
  number is not declared anywhere in this repository.

**Fixed the same day, and verified by re-injecting the same failure.** Two
independent causes, both needed:

- `--stuck-request-timeout 45s`. restic's 5m default outlived the unit, so
  systemd killed the run before restic reached its own error path — which is
  also why `TimeoutStartSec=600` never applied.
- The `snapshots` probe discarded stderr. It is the FIRST call to touch R2, so
  it is exactly where a bad credential is discovered, and its stderr was the
  only explanation the run would ever produce.

Same injection, after the fix:

```
Stat(<config/>) returned error, retrying after 49.1s: Stat: The request
signature we calculated does not match the signature you provided. Check your
secret access key and signing method.
```

180 seconds of silence became a named cause. The operator now gets the reason
in the envelope's journal tail rather than a run that ends mid-sentence.

#### A measurement error I made twice

`systemctl show -p Result` returns the PREVIOUS run's verdict while a unit is
`activating`, and `make backup-node` returns before a hung unit settles. I read
`Result=success` on an injected failure twice before checking `ActiveState`.
`InvocationID` is the tell: empty means the unit has never run, so a `success`
beside it is a default rather than a result.

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

> **Supersedes R4 of the parallel lane's Part 0** (`origin/docs/backup-044-part0`,
> ported here by BACKUP-047/#1123). That lane answered the same question with
> `Before=kubelab-compose.service` and a per-node caveat. It is wrong: this section's
> measurement shows `unless-stopped` resurrects containers at the `docker.service`
> mark on an unclean shutdown, 23 s earlier than the compose unit, so ordering against
> the compose unit does not hold. `Before=docker.service` is the answer, and it also
> yields a quiescent database. Recorded rather than silently dropped, because the two
> lanes reached opposite conclusions from the same starting point and only one ran the
> unclean-shutdown case.

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

**The deployable cap: was blocked, root cause verified, then unblocked the same session.** Two
attempts to obtain a number failed before the reason became clear, and the failures are recorded
because the second one nearly shipped a false result. The resulting number is in
"The cap, measured" below:

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

#### The cap, measured (2026-08-15, after the prerequisite landed)

The prerequisite was fixed the same session — `ANSIBLE-040` (#1101, PR #1103) gave the node the
memory cgroup controller, and the control experiment inverted: 300MB under `MemoryMax=64M` now
dies with exit 137, while 32MB under the same cap survives. Two-sided, so the oracle discriminates
rather than merely killing everything.

The descent sweep was then re-run unchanged, against the real workload (back up the live Uptime
Kuma volume, then `restic check`):

| cap | backup | check | verdict |
|---|---|---|---|
| 192M | ok | ok | survives |
| 128M | ok | ok | survives |
| 96M | ok | ok | survives |
| 64M | ok | ok | survives |
| 48M | ok | ok | survives |
| 32M | ok | ok | survives |
| 24M | ok | ok | survives |
| **16M** | **FAIL(137)** | **FAIL(137)** | **breaks here** |

The floor is between 16M and 24M for a 7.9M repository. Compare the same sweep before the
controller existed, which reported survival at every level including 16M — the difference between
a test and a test that checks something.

**Recommended deployable cap: `MemoryMax=128M`, with `MemorySwapMax=0`.** That is >5x the measured
floor and ~14% of the node's RAM, so it absorbs index growth as the repository accumulates
snapshots while still bounding a runaway well below the point where Uptime Kuma is at risk. The
measurement is a floor, not a ceiling: restic's index scales with repository size, so this should
be re-checked if the RPi3's repo ever grows far beyond the ~8M seen here.

One incidental observation worth carrying into AC2: the payload measured 21.642 MiB before the
reboot and 17.591 MiB after it, because the restart checkpointed SQLite's WAL. The size of what
is on disk depends on WAL state, which is a concrete argument for `sqlite3 .backup` rather than a
file copy — the proposal asserted this; the reboot demonstrated it by accident.

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

### R2 — the destination exists and was proven before anything depended on it

**Settled 2026-08-16, shipped in #1116.** Bucket `kubelab-backups`, non-secret values as
SSOT at `backup.r2` in `common.yaml`, credentials in SOPS at `backup.r2.access_key_id` /
`backup.r2.secret_access_key`.

Two details worth keeping out of the transcript and in prose, because they are decisions
rather than outputs:

- The credential is an **Account** API token, not a User API token. A user token goes
  inactive if its user leaves the account — for a backup credential that is a silent-failure
  vector, and the failure would surface at restore time.
- `backup.r2`, not `infra.backup_r2`. `infra.*` is an injection point, not a namespace:
  the K8s generator flattens everything under it into `INFRA_*` keys in *every* component's
  ConfigMap (ADR-036). The first attempt used it and drifted both overlays
  (`docs/lessons/ci-automation/lesson-004-*`).

The proof is a command rather than a pasted run, so it re-executes in the reader's present
instead of expiring: `make backup-verify-destination` probes scope, reach, and a
write/read/sha256/delete round-trip with a throwaway object; `make backup-verify-restic`
runs an init/backup/snapshots/check lifecycle and removes the probe repository. Credential
values are passed through the environment and never appear in argv. Procedure and the
disaster case are in `docs/runbooks/offsite-backup-restore.md`.

---

### R6 — where to exercise the restore: SETTLED

**Adopted: an ephemeral instance, as the 2026-08-10 Gitea research proposes.** The
restore target is never the live data directory.

The reasoning is short enough to state fully: restoring over `/opt/gitea/data` to
prove the backup works risks the thing being protected, and if the snapshot turns
out to be the wrong one the evidence is already destroyed. Restoring into a
scratch location costs nothing and keeps both the backup and the original.

It doubles as the #492 DR drill, which is worth reusing but not worth expanding
this spec to close. Recorded in `docs/runbooks/offsite-backup-restore.md` as the
standing procedure, including the `PRAGMA integrity_check` step for SQLite
consumers — a restore that produces a file is not the same as a restore that
produces a *readable* database.

---

### AC7 — the Class A operations question: MEASURED, and the concern was overstated

Per-operation cost, counted server-side from MinIO's `minio_api_requests_total`
(PutObject, ListObjectsV2, DeleteObject and the multipart verbs — R2's Class A
set):

| Operation | Class A ops |
|---|---|
| `backup` (incremental) | 110 |
| `snapshots` | 60 |
| `check` | 80 |

Projected against R2's 1,000,000 free Class A operations per month, over four
nodes (two always-on hourly, two on-demand in bursts — 1,640 runs/month):

| Schedule | Class A / month | Free tier used |
|---|---|---|
| `check` on every run (AC7 as written) | 311,600 | **31.2%** |
| `check` weekly | 181,680 | 18.2% |
| Backup every 4h + `check` weekly | 62,880 | **6.3%** |

**Correcting an earlier claim made in this spec's own discussion:** per-run
`check` was described as scraping the million. Measured, it is 31% of it. AC7 as
written is affordable and does not need to change on cost grounds alone.

**The larger lever is the schedule, not the check.** Dropping `check` to weekly
saves 130k operations; dropping the always-on nodes from hourly to every four
hours saves 119k more — and costs nothing against the requirement, because #452
ratifies Tier 1 at **RPO < 6h** and hourly was already over-delivering against it.
Both together land at 6.3% of the free tier, leaving room for the repository to
grow the per-operation cost several times over before the tier is at risk.

That growth is the reason to take the headroom rather than bank the 31%: both
`check` and `backup` list pack files, so their cost rises with repository size,
and this rig measured a small repository. A design sitting at a third of the
budget on day one has nowhere to go.

**Recommendation for `tasks.md`:** backup every 4h on always-on nodes (still
inside the ratified RPO), uptime-bounded hourly on on-demand nodes as the
proposal specifies, and `check` weekly rather than per-run. Operator decision,
recorded here with the arithmetic behind it.

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

### New finding — none of the pipeline's prerequisites exist on any node

Not a risk `proposal.md` raised, and it changes the shape of the implementation.

| Node | `sqlite3` | `restic` | Memory available |
|---|---|---|---|
| RPi3 | MISSING | MISSING | 428 MB of 905 MB |
| Beelink | MISSING | MISSING | 6720 MB of 7716 MB |
| ace1 | MISSING | MISSING | 9224 MB of 11741 MB |
| VPS | MISSING | MISSING | 4884 MB of 7729 MB |

Every node is `aarch64`. The VPS is reached as `deployer`
(`networking.ssh_users.cloud`), the homelab nodes as `manu`.

`sqlite3` is the mechanism behind AC2 — "each of the four live SQLite databases
is snapshotted with `sqlite3 .backup`" — and it is present on none of the four
nodes that must run it. `restic` likewise. The Ansible role therefore owns
installing both, which is ordinary work, with two consequences worth naming
before `tasks.md` is drafted:

- The install itself has a cost on the RPi3, and it lands on the node with the
  least headroom.
- Package availability is a Debian 13 / `aarch64` question on every node, so the
  role cannot assume a distribution default that happened to work on a
  development machine.

### New finding — the proposal cannot satisfy its own AC1

Surfaced by the operator asking what, concretely, is being backed up.

AC1 requires "every ratified Tier 1 **and Tier 2** item present in its node's R2
repository". #1090 records the ratified tiers as:

- **T1:** Headscale, Authelia, Gitea, Uptime Kuma, Postgres
- **T2:** Grafana, n8n, CrowdSec db, Pi-hole FTL

The proposal's consumer table covers four nodes: VPS (Headscale, Authelia,
Postgres), Beelink (Gitea), RPi3 (Uptime Kuma), RPi4 (Pi-hole FTL).

**Three ratified Tier 2 items appear nowhere in it: Grafana, n8n and the CrowdSec
database.** As written, the spec builds a pipeline that cannot meet its own
acceptance criterion.

The reason they were missed is structural rather than careless, and it matters
for how they get added. Those three do not live in a node's filesystem — they are
**Kubernetes PVCs**, and the existing prod CronJob already backs two of them up:

```
$ grep claimName infra/k8s/overlays/prod/backup.yaml
                claimName: authelia-data
                claimName: n8n-data

$ grep minio infra/k8s/overlays/prod/backup.yaml
  mc alias set backup http://minio:9000 ...
```

So there is a **fifth consumer class the proposal has no row for**: the K3s
cluster itself, whose state is PVCs rather than paths, and whose backup currently
targets in-cluster MinIO — the destination ADR-061:96 identifies as the thing
coercing MinIO to always-on, and which was never an offsite copy.

**Authelia is in both places and the proposal has it in the wrong one.** It is
listed under "VPS" as though it were a node-level directory, but it is
`authelia-data`, a PVC. The mechanism for backing it up is not the one the
proposal describes for that node.

This does not change the destination, the credentials, the retention model or any
Part 0 answer. It changes the *consumer inventory*, and `tasks.md` must not be
drafted against the current table. Two options for the operator:

1. **Extend this spec** with a PVC consumer class, bringing Grafana, n8n and
   CrowdSec into the R2 pipeline and retiring the MinIO CronJob's remaining
   consumers — which is also what eventually releases #972.
2. **Narrow AC1** to Tier 1 plus Pi-hole FTL, and file the PVC class as the next
   ticket in #1090's sequence.

Option 1 satisfies the criterion as ratified; option 2 ships sooner and keeps the
spec's node-level shape coherent. Either is defensible, neither can be skipped —
`tasks.md` written against the current table would build something that fails its
own AC1 review.

**Resolved 2026-08-15: option 2.** The decision was written on the Part 0 branch and
reached master in pieces, with the criterion itself left behind — so the finding above
sat next to an AC that still asked for what it had just proved impossible. Three
independent places in this tree already act on option 2: **BACKUP-046 (#1111)** exists
and is scoped to the PVC consumer class; `tasks.md`'s "Follow-ups, not this spec" names
it as the next ticket in #1090's sequence; and the out-of-scope note states the split is
**by mechanism**, because the tier axis cannot make it — Authelia and Postgres are Tier 1
*and* PVCs. AC1 is narrowed to the node-path class here, in `tasks.md` Part 6, and in the
evidence checklist above. Two things the label hides. First, option 2's own wording
overreaches: "narrow AC1 to Tier 1 plus Pi-hole FTL" still contains Authelia and
Postgres, the two members it was trying to exclude — the applied narrowing is
option 2's *intent*, stated by mechanism instead of by tier. Second, the consumer
table this finding criticises has since been corrected: it now lists four
node-path consumers and no PVCs, and the section above it names the class
explicitly, so the narrowed AC1's referent is coherent. The finding's own
description of that table is therefore historical, and is left as written. Reverting is a one-line edit in each of the three, and the
finding above is deliberately left intact so the reasoning survives the decision.

**AC9 arrives with it.** The same Part 0 pass added a ninth criterion — a run that
*never happened* is reported — which never reached master either. It is not a
restatement of AC4: AC4 covers a run that fails and therefore emits something, while a
node whose timer stopped emits nothing at all, and every check that asserts only "recent
snapshots look healthy" agrees with it. That is the same shape as the gates this repo
spent 2026-08-17 fixing — a control that cannot exhibit the failure it guards.

---

### Part 4 — first real deploy, and three defects merged code had never hit

Part 3's role (#1179) merged with CI green and no test ever invoked it against real
hardware — `make backup ENV=prod` had not been run since merge. Deploying it now,
to measure real capture/ship timing for the AC5 trigger-model decision below,
surfaced three environment-dependent failures, one per node class, none of them
caught by lint, `--syntax-check`, or the unit tests:

1. **rpi3 and rpi4 (apt):** `Install sqlite3` failed, "No package matching
   'sqlite3' is available" — a cold apt cache, never refreshed because the task
   omitted `update_cache`. VPS and Beelink happened to have a warm cache already
   and never exposed it. Fixed: `update_cache: true`, `cache_valid_time: 3600`,
   matching the existing convention in `base_system` and `dev_node`.
2. **rpi4 only (bzip2):** restic install failed, `bunzip2: not found`. rpi4's
   apt state has `libbz2-1.0` pinned at a build the configured repo no longer
   carries (`apt-cache policy`: installed `1.0.8-5.1build0.1`, candidate
   `1.0.8-5.1`), so `apt install bzip2` fails on an unresolved dependency —
   fixing it would mean changing rpi4's package state, out of scope here.
   Fixed instead by removing the dependency on the `bunzip2` binary entirely:
   decompression now goes through `python3 -c "import bz2..."`, since every
   node Ansible manages already guarantees a `python3` interpreter
   (`ansible_python_interpreter`). Fleet-wide fix, not an rpi4 special case.
3. **All four nodes (ship unit):** `node-backup-ship.service` has no `User=`,
   so it runs as root with no `HOME` — restic's own error: "unable to locate
   cache directory: neither $XDG_CACHE_HOME nor $HOME are defined". It failed
   *after* successfully creating the R2 repository (`restic init` doesn't need
   the cache; `backup` does), which is the failure mode this pipeline exists to
   catch surfacing in its own deploy: a report that looked like a repository
   was live when nothing had been shipped to it. Fixed: `Environment=HOME=/root`
   in the unit.

All three are runtime defects in already-merged Part 3 code, not Part 4 design.
None is destructive — sqlite3/bzip2 are additive package installs, the
decompression change and the environment variable are role-local. Sequencing
note for whoever re-reads this: mid-fix, `systemctl show <unit> -p Environment`
briefly reported empty against a file on disk that already had it, which read
like a real bug for one investigation cycle. It was not — a stale in-memory
unit from a prior daemon-reload, resolved by rerunning `daemon-reload`
explicitly before the next `systemctl show`. Recorded so the next person
doesn't re-spend the cycle.

**Wants=/After= design, proven live.** rpi3, 2026-08-21 03:21 (local, CEST):

```
03:21:11  Starting node-backup-capture.service
03:21:14  capture complete: 18M
03:21:14  Starting node-backup-ship.service   <- pulled in by Wants=, ordered by After=
03:21:26  ship complete
```

A single `systemctl start node-backup-ship.service` — the shape the AC1 timer
will invoke — correctly drives the whole capture-then-ship cycle with no
separate capture timer. This settles the Requires=/Wants= question Part 3 left
open: `Wants=` lets ship run and refuse on a missing sentinel with the reason in
the log an operator is actually reading, rather than silently blocking ship at
the systemd level on a capture failure.

**Timing, all four nodes, deployed 2026-08-21.** Every run below is a **first
snapshot** (`no parent snapshot found, will read all files`) — vps, beelink and
rpi4's numbers include one-time `restic init` (repository creation, ~3-5s).
rpi3's does not (its repository already existed from an earlier failed attempt
during this same session). Steady-state incremental runs will be faster on all
four; `forget --prune` will slow as snapshot history accumulates. Do not treat
these as steady-state numbers.

| Node | Class | Capture | Ship (incl. init where noted) | Payload | Files |
|---|---|---|---|---|---|
| rpi3 | always-on | 3s | 12s | 18M / 4.234 MiB stored | 4 |
| kubelab-vps | always-on | 1s | 13s (incl. ~5s init) | 140K / 16.629 KiB stored | 5 |
| beelink | on-demand | <1s | 8s (incl. ~4s init) | 2.3M / 50.817 KiB stored | 24 |
| rpi4 | on-demand | 1s | 12s (incl. ~3s init) | 24M / 8.697 MiB stored | 25 |

Beelink's snapshot verified by content, not size alone (this session's own
recurring failure mode is a component reporting success over the wrong data):
`restic ls latest` against beelink's repository lists `gitea.db`, the git
repositories directory, the JWT signing key, and all three SSH host keys —
the actual critical subset, not an empty or partial capture.

**Memory, measured against R-B's 128M cap (rpi3 only).** The ship run above
peaked at **90M** (`systemd[1]: node-backup-ship.service: ... 90M memory
peak`); an earlier failed attempt on the same node peaked at 75.7M. Real
margin over the current repository size is ~1.4x, not the >5x headroom
`defaults/main.yml` claims over the R-B floor (16-24M) — that comparison was
against restic's baseline footprint before any real repository existed. Not
acted on here (no-guessing-infra: this is the measurement that decision
needs, not the decision itself) — flagged for the operator, since a grown
rpi3 repository pushing past 128M gets restic OOM-killed on the monitoring-
of-record node.

**AC5, the shutdown-ordering question — answered.**
Beelink and rpi4's full first-run cycles (capture+ship) completed in 8s and
12s respectively; steady-state incremental runs will be shorter. That is well
inside a systemd shutdown budget, which reverses the concern this spec's
handoff carried into Part 4 ("only matters if the node never returns, and in
that case it's worthless unless it also ships, which needs the measured ship
duration") — shipping on graceful shutdown is measured as feasible, not
merely theoretical. The ordering itself uses the mechanism this section's
boot-side finding already established: a unit ordered `After=X` stops
*before* X on shutdown (the inverse of start order), so a `RemainAfterExit`
unit with its work in `ExecStop=`, ordered `After=` whichever unit actually
stops the writer, runs while that writer is still live. Not a fleet-wide
`docker.service` constant: Beelink's `kubelab-compose.service` is itself
`After=docker.service` and stops itself before dockerd does, on its own
schedule, so ordering against `docker.service` directly would race it with
no guaranteed outcome — the new unit orders against `kubelab-compose.service`
there, and against `docker.service` on RPi4, which has no equivalent
compose-wrapping unit (its containers are reaped by dockerd itself).

**Deployed and live, 2026-08-21 — operator-approved go-live, not a design
default.** All four nodes: periodic ship timer and weekly integrity-check
timer both `enabled` + `active`, confirmed via `systemctl list-timers` with
the expected next-run times (rpi3's next `OnCalendar` fire: 2026-08-21
04:00 CEST). On-demand nodes only: capture `enabled` with `Before=docker.service`
loaded (`systemctl show`, confirmed on rpi4), and the shutdown-snapshot unit
`active` with `After=kubelab-compose.service` (beelink) /
`After=docker.service` (rpi4) loaded correctly per node. `restic` in the
role's decompress step, the ship unit's `Environment=HOME`, and the apt
cache fix travel through the same deploy but are tracked as a separate
change (#1200) since they are runtime-defect fixes to already-merged code,
independent of Part 4's scheduling itself.

**Still open, deliberately.** The real power-cycle demonstration of the
on-demand trigger model — tasks.md's own bar for AC5, "not by configuration
review" — has not been run. Structural verification (dry-run, `systemctl
show`, unit tests) is not a substitute for it; it is what makes the eventual
power-cycle a confirmation rather than a first real test. Rollback, if
needed before that demonstration: `systemctl disable --now
node-backup-ship.timer node-backup-ship-check.timer` on every node, plus
`node-backup-shutdown.service` and `node-backup-capture.service` on the
on-demand pair — the capture/ship mechanism itself (Part 3) is unaffected
and can keep being triggered by hand.
