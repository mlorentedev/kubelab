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

### R1, R2, R4, R6 — not yet settled

- **R1** (restic repository password circularity) — operator decision, options
  not yet presented. Blocked on analysis of whether #479 already rejected an
  R2-side escrow.
- **R2** (Cloudflare R2 bucket and credentials) — operator action; the bucket
  does not exist. `SECRET_CATALOG` registration prepared separately, with the
  ANSIBLE-033 `envs` failure mode checked.
- **R4** (`Persistent=true` does not order the boot snapshot before the first
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
