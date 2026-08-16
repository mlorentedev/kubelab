---
tags: [spec, verification, backup]
created: "2026-08-16"
---

# Verification - BACKUP-044-critical-subset-pipeline

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof.

- [ ] AC1 (every Tier 1/Tier 2 item present in its node's R2 repository) -> implementation
- [ ] AC2 (each live SQLite snapshotted with `sqlite3 .backup`) -> implementation
- [ ] AC3 (restore exercised end-to-end, transcript captured) -> implementation
- [ ] AC4 (failed backup alerts; missed window on a powered-off node does not) -> implementation
- [ ] AC5 (on-demand trigger exercised across a real power cycle) -> implementation
- [ ] AC6 (sources enumerated from an SSOT allow-list) -> implementation
- [ ] AC7 (`restic check` passes as part of the scheduled run) -> implementation
- [ ] AC8 (no new consumer of `minio:9000`) -> implementation

## Open questions, settled

Part 0. Every answer below was measured against a live node, never read off
documentation. A settled question with no transcript is an assertion.

Fleet state at time of measurement (2026-08-16, ~02:45Z): ace1, beelink, VPS and
RPi3 all up on the tailnet. aws1 absent — Spot reclaim, #1066. Homelab powered on.

### R5 — which Uptime Kuma volume is live: SETTLED

The live volume is **`uptime_kuma_data`**. The discriminator is the running
container's mount, and nothing else:

```
$ docker inspect uptime-kuma --format '{{range .Mounts}}{{.Type}} {{.Name}} -> {{.Destination}}{{end}}'
volume uptime_kuma_data -> /app/data
```

Both volumes exist on the RPi3, and their contents separate cleanly by mtime:

| Volume | Size | `kuma.db` last modified | Status |
|---|---|---|---|
| `uptime_kuma_data` | 18M | 2026-08-16 02:42 | **live** — mounted, writing now |
| `uptime-kuma_uptime_kuma_data` | 26M | 2026-03-28 04:32 | orphan (#1092 instance 1), frozen |

**The orphan is larger than the live volume — 26M against 18M.** This is the
finding that matters for AC6, and it is worse than `proposal.md` anticipated. The
proposal worried that a backup written against the wrong name "would pass any
check asserting only that a non-empty backup exists". It would also pass a check
asserting the *larger* or the *more complete-looking* copy, and it would pass a
check comparing against last week's size. Size, name plausibility and apparent
completeness all point the wrong way here; only the live mount and the mtime
point right.

So the allow-list must name `uptime_kuma_data` explicitly, and the runbook must
record that the wrong volume is the bigger one. Recorded here so the discriminator
survives even if #1092's orphan is never deleted.

### R3 — restic's memory footprint on the RPi3: NOT SETTLED, and the node is tighter than assumed

Measured, but the question is not yet answered — see "why a naive trial would
mislead" below.

```
$ free -m
               total        used        free      shared  buff/cache   available
Mem:             905         476         132           1         361         428
Swap:            904          26         878

$ grep -E "^(MemTotal|MemAvailable|Committed_AS):" /proc/meminfo
MemTotal:         926828 kB
MemAvailable:     438940 kB
Committed_AS:    1435792 kB
```

Three corrections to the premise in `proposal.md`:

1. **It is not a 1GB node in any usable sense.** 905 MB total, **428 MB
   available**. The budget for a backup process is the 428, not the 905.
2. **The node is already overcommitted by roughly 1.55x** — `Committed_AS` 1.4 GB
   against 926 MB of RAM, with 904 MB of swap absorbing the difference. Adding a
   memory-hungry process to a node in this state risks swap thrash on an SD card,
   which degrades the service rather than killing it — a failure mode that is
   harder to notice than an OOM kill, on the node that is the monitoring of
   record for prod.
3. Platform: Debian 13 (trixie), `aarch64`, 20 GB free on `/`. Disk headroom is
   not a constraint; memory is.

**Why a naive trial would produce a falsely reassuring number.** `proposal.md`
already states the mechanism — restic's index is held in memory and scales with
*repository* size, not with the size of the snapshot being written. A trial
against a fresh scratch repository holding one 18 MB snapshot would therefore
measure almost nothing and report "fits comfortably", which is precisely the
answer that would be wrong in six months. Measuring this honestly requires a
repository grown to a realistic snapshot count, not a first backup. **Designing
that trial is the remaining Part 0 work on R3.**

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

### R2 — the R2 destination: SETTLED, and smoke-tested before any pipeline exists

Bucket `kubelab-backups` created, Account API token issued (not a User API
token: a user token goes inactive if its user leaves the account, which for a
backup credential is a silent-failure vector). Credentials in SOPS at
`backup.r2.access_key_id` / `backup.r2.secret_access_key`; non-secret values as
SSOT at `infra.backup_r2` in `common.yaml`.

Smoke-tested from the workstation against the live bucket, before a line of the
pipeline was written. Credential values were read from SOPS into the environment
and never printed:

```
=== 1. authenticate + what can this token see? ===
  list-buckets refused (expected for a bucket-scoped token):
    An error occurred (AccessDenied) when calling the ListBuckets operation: Access Denied

=== 2. can it see the target bucket? ===
  PASS: kubelab-backups is reachable

=== 3. write / read / delete round-trip (1 KB throwaway) ===
  write:  PASS
  read:   PASS
  integrity: PASS (sha256 match)
  delete: PASS
  cleanup verified: PASS (object gone)
```

Three things this establishes that a configuration review could not:

1. **The token is genuinely bucket-scoped.** `ListBuckets` is refused while the
   target bucket is reachable — so a compromise of this credential cannot reach
   any other bucket in the account. Scoping that is claimed but never exercised
   is an assumption.
2. **Delete works.** This is the one that would have failed late and quietly: a
   read-write token without delete lets backups run green for weeks and only
   fails when `restic forget`/`prune` first tries to reclaim space, with a full
   bucket and a retention policy that has never actually retained anything.
3. **The credential shape matches the documented derivation** — 32-char key id,
   64-char secret, consistent with the secret being the hex SHA-256 of the token
   value. That matters for recovery: the secret can be re-derived from the token
   value, so the escrow copy of the token value is itself a recovery path.

Ordering note, recorded because the instinct runs the other way: the first object
written to a new backup destination should be the *least* sensitive thing
available, not the most. Testing with real state — or worse, a password-manager
export — puts the most valuable data in a bucket whose permissions, retention and
delete path are all still unproven.

**Not yet codified.** The smoke test ran from a scratchpad script with the
account id and bucket inlined. Before it is reused it must read them from
`infra.backup_r2` in `common.yaml`, or it becomes a second source of truth for
values that already have one.

### R1 — partially settled: the escrow decision

The circularity is real and is now broken on one side. SOPS is decrypted by an
age key that a disaster destroys, so credentials stored *only* in SOPS make the
backups unreachable in exactly the scenario they exist for — intact and
unopenable.

**Decided: a manual Bitwarden item as an independent trust root** (operator
created it 2026-08-16), holding the account id, bucket, both S3 credentials, and
the R2 token value. Bitwarden recovers from a master password on any machine,
depending on no physical artefact.

Deliberately **not** registered in the `dotf secrets` registry. An escrow whose
read path requires a dotfiles checkout, a running `bw serve` daemon and a working
`dotf secrets run` — which fails roughly one attempt in three today
(dotfiles#988) — has added three dependencies to the one path that must work when
everything else has failed. Nothing automated needs this copy; that is the point.

Prior art: #479 already proposed exactly this shape, naming Vaultwarden. That
target does not exist — Vaultwarden survives only as toolkit functions whose
restore is literally `"Vaultwarden restore not yet implemented"` — and
self-hosting the escrow would reintroduce the circularity on different
infrastructure. Cloud Bitwarden does not.

**R1 is now fully closed.** The restic repository password was generated by
`make backup-generate-password` (RANDOM_TOKEN, 48 bytes, never printed),
registered in `SECRET_CATALOG` as `backup.restic_password` with `envs=("prod",)`,
and copied by the operator into the same Bitwarden item as the R2 credentials
(2026-08-16). One item, because they are one recovery bundle: without the R2
credentials you cannot reach the bucket, and without the password you cannot read
what is in it. Splitting them only creates the possibility of finding half.

Generated rather than operator-chosen deliberately: nothing ever types this
password. restic reads it from the environment, which reads it from SOPS. A
human-chosen value would trade entropy for a memorability that has no consumer.

**Why the escrow is a manual Bitwarden item and not `dotf secrets`** — this was
re-examined at the operator's prompting and the answer got stronger. The dotfiles
registry's own header records that its backend is **age today**, with Bitwarden
only a migration target (`backend: age (current) | bw (target, ADR-028 Phase 3)`;
`bw:` is "dormant while backend is age"). Registering the escrow there would
store it in an age-encrypted file — *the same trust root whose circularity this
risk exists to break*. It would traverse the whole argument and arrive back at
the start. Secondarily, that registry is one entry per environment variable an
app consumes, and this value is consumed by Ansible out of SOPS, not by an app
out of the environment.

Rotation carries an ordering constraint recorded in the spec's `rotate_note`
rather than only here, because the catalog is where someone will look during a
rotation: `restic key add` must run on every repository *before* this value
changes. restic derives the key that unlocks an internal master key, so adding a
second password is cheap — but only in that order. Replacing it first locks you
out of every snapshot already taken.

### R4 — boot ordering: the answer differs per node, and the spec assumed one

`proposal.md` treats "backup on power-on, before the service accepts its first
write" as a single design question. It is two, because the two on-demand nodes
start their containers by different mechanisms:

| Node | How containers start | Orderable against |
|---|---|---|
| Beelink | `kubelab-compose.service` (systemd oneshot, `docker compose up -d`) | **the unit itself** — `Before=kubelab-compose.service` |
| RPi4 | Docker restart policy only; the `coredns` role ships no systemd unit | **only `docker.service`** |

So the Beelink has a genuine ordering relationship available and the RPi4 does
not. On the RPi4 the only orderable target is `docker.service` itself, which
means the snapshot runs before Docker starts at all — the database is guaranteed
quiescent, which is *better* for consistency, but it is a different design that
cannot use a running container.

Either way `Persistent=true` is the wrong instrument: it controls *when a missed
timer catches up*, not *what it runs before*. The ordering must be an explicit
`Before=`/`After=` relationship. Confirming it across a real power cycle belongs
to AC5 in implementation, not to Part 0.

### R3 — restic's memory on the RPi3: SETTLED, and it fits

Measured on a local MinIO rig rather than against R2, so the measurement cost no
Class A operations and the repository could be grown freely. Peak RSS via
`/usr/bin/time`:

| Operation | Fresh repository | Grown repository (42 snapshots) |
|---|---|---|
| `backup` (first, 18 MB) | **158.1 MB** | — |
| `backup` (incremental) | 59.0 MB | **58.3 MB** |
| `snapshots` | 57.1 MB | 57.7 MB |
| `check` | 58.0 MB | **58.8 MB** |
| `forget --prune` | — | 64.4 MB |

**The premise the risk was written on does not hold at this scale.** `proposal.md`
warned that restic's index is held in memory and scales with repository size, so
a naive first-snapshot trial would mislead. The rig was built specifically to
catch that — and memory stayed flat from 1 to 42 snapshots: `check` moved 58.0 →
58.8 MB. The steady-state working set is ~60 MB against the RPi3's **428 MB
available**, roughly a 7x margin.

The one number that stands out is the *first* backup at 158 MB, chunking 18 MB of
incompressible random data. That is a one-off and still fits, but it is the run
to watch on the first deployment, not the recurring ones.

**Honest limit of this measurement:** 42 snapshots over ~20 MB is not a year of
hourly backups over several GB. Index memory tracks blob and pack count, and this
rig did not reach production scale. What it establishes is the *shape* — flat, not
climbing — which is the claim the risk actually needed. Re-measure on the device
after the repository has real history; do not treat 60 MB as a permanent ceiling.

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

### Superseded — the earlier open list

- **R1** — escrow settled above; the repository password itself remains.
  not yet presented. Blocked on analysis of whether #479 already rejected an
  R2-side escrow.
- **R2** — settled above.
  does not exist. `SECRET_CATALOG` registration prepared separately, with the
  ANSIBLE-033 `envs` failure mode checked.
- **R4** — settled above.
  write) — design read outstanding. Full proof needs a power cycle, which belongs
  to AC5 in implementation rather than to Part 0.
- **R6** (restore target) — the 2026-08-10 Gitea research proposes an ephemeral
  instance; adopting it is a one-line decision, recorded when R1 is.

## Test status

Not applicable yet — Part 0 is measurement, and no code has been written.

## Decisions made during implementation

Not started.

## Promotion candidates

Deferred until the spec is complete.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/<feature-id>/` -> `specs/archive/<feature-id>/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
