---
id: lesson-700-a-sqlite-snapshot-costs-the-same-whatever-the-gap
type: lesson
status: active
created: "2026-11-03"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2]
---

# A snapshot of a live SQLite file costs about the same whatever the gap, so the snapshot count sets the bill

**Context**: R2 storage grew 0.35 GB a day and passed the 8 GB alert (#3035). The 2026-08-16 retention approval assumed restic's dedup made frequent snapshots nearly free.

**Problem**: For a SQLite file that is written all the time, it does not. `restic diff` against the latest snapshot, from the one 1, 4 and 24 snapshots before: rpi4 (`pihole-FTL.db`) 31, 32 and 44 MB; beelink (`gitea.db`) 174, 183 and 252 MB. Scattered page writes touch most of restic's content-defined chunks, so each snapshot re-stores a large part of the file however little changed. With the 30-day lock, every hourly snapshot is also kept for 31 days, so retention cannot recover it. A wrong declaration multiplied it: rpi4 kept `location: on-demand` after ADR-075 made it the always-on edge, so it shipped hourly instead of every 4 hours (#3037).

**Solution**: Declare rpi4 `always-on`, which moves it to `OnCalendar=*-*-* 0/4:00:00`. `tests/test_edge_is_always_on.py` holds every `gateway` node to it.

**Rule**: Before approving a cadence for a database source, measure the bytes one snapshot adds at two different gaps. If they are close, the cost is per snapshot: choose the cadence from the RPO, and keep telemetry and rebuildable indexes out of the backup.

**Tags**: `#restic` `#r2` `#backup`
