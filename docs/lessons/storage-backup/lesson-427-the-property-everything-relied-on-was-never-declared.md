---
id: lesson-427-the-property-everything-relied-on-was-never-declared
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, sqlite, verification, ansible]
---

# A default nobody chose is not a decision, and four backups were relying on one

**Context**: `node-backup-capture.sh` snapshots live SQLite databases with
`sqlite3 .backup` rather than copying the file, and the script says why:

```sh
# Live SQLite snapshot: `.backup` is WAL-aware and produces a single
# consistent file, unlike a raw copy of a database mid-write
```

The statement is true. `.backup` *is* WAL-aware. Nothing had ever checked it was
also true of the **database**.

**Problem**: On 2026-09-04 at 06:23:58 the Beelink's capture failed:

```
node-backup-capture.sh[83488]: Error: database is locked
node-backup-ship.sh[83492]: no capture sentinel -- refusing to ship a partial backup
```

`gitea.db-wal` and `gitea.db-shm` were both **absent**, so Gitea was in
rollback-journal mode, where a writer's commit takes an EXCLUSIVE lock that
refuses readers. Gitea's own log for that second showed `act_runner` posting
`UpdateTask` and `UpdateLog` **every second** for a running job. `.backup` ran
with no busy timeout and was refused at the first contended instant.

Measuring the rest of the fleet is what turned an incident into a finding:

```
beelink / gitea        delete   <- failed
vps / authelia         delete   <- had not failed yet
rpi3 / uptime_kuma     WAL
rpi4 / pihole          WAL
vps / headscale        WAL
vps / n8n              WAL
```

**Four of six were in WAL purely by each application's own default.** Nobody
chose it, no file declared it, and no test asserted it. That is why the failure
looked random: whether a backup succeeded depended on which default an image
happened to ship, and on whether that database was under sustained write during
the capture minute. Authelia had not failed because few people authenticate at
06:00 — which makes it *unmeasured*, not safe.

**Solution**: Declare it where the application allows, cover the rest, and make a
new source impossible to add silently.

- `GITEA__database__SQLITE_JOURNAL_MODE: "WAL"`. Idempotent by construction: the
  journal mode is persisted **inside the database file**, so re-applying changes
  nothing and needs no guard task. Verified by consequence — `PRAGMA
  journal_mode` returned `wal`, both siblings appeared on disk, and a second
  Ansible pass returned `changed=0`.
- `sqlite3 -cmd ".timeout 10000"` plus three retries in the capture, covering
  what a declaration cannot: an application with no such setting (Authelia's
  `storage.local` accepts only `path`, hence #1632), and the `SQLITE_BUSY` a WAL
  checkpoint can still return.
- A test asserting the **set** of declared sources, so a seventh fails until
  someone measures its mode. Deliberately *not* "every source is in WAL" — the
  repository cannot see a journal mode living inside a database file on a node,
  and a static test claiming to would assert something it never checked.

**Rule**: **A property your system depends on, that nothing declares, is a
coincidence you are treating as a guarantee.** The tell is a comment that
correctly describes a *mechanism* while silently assuming a *state*: `.backup` is
WAL-aware, and the sentence is true no matter what mode the database is in. Ask
of any such line — *what would have to be true elsewhere for this to hold, and
who asserts it?* Where the answer is "the upstream default", it is not a
decision, and it can change under you in a version bump nobody reads.

The failure mode is specifically that it works. Four of the six were fine, for
years, so nothing prompted the question; the two that were not stayed invisible
until one of them met sustained write pressure. A property that holds by luck
holds until the load changes, and then fails in whichever instance you were least
watching.

Same shape as
[lesson-422](../process-method/lesson-422-a-stale-blocker-reads-exactly-like-a-live-one.md)
seen from the other side. There, a note described a condition that had ceased to
be true and nobody re-measured. Here, nobody had measured in the first place —
and both are settled by the same move: run the thing and read the result, rather
than reasoning from what the surrounding text says.

**Worth stating separately**: the ship step **refused** rather than failed. It
found no capture sentinel and declined to send a partial backup, which is the
half of the system that worked exactly as designed and is why nothing was lost —
the 05:19 cycle was complete. A guard that fails closed converts a silent
corruption into a visible incident, which is the entire trade it exists to make.

**Tags**: `#sqlite` `#backup` `#verification` `#issue-1630` `#issue-1632`
`#pr-1631`
