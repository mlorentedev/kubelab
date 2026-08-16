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

### R6 — not yet settled

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
