---
id: lesson-524-size-a-backup-bucket-by-listing-it-not-by-walking-its-snapshots
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, rclone, observability]
---

# Size a backup bucket by listing its objects, not by walking its snapshots

**Context**: The R2 watcher reported each repository's size with `restic stats
--mode raw-data`, and the free-tier alert paged on the fleet sum (BACKUP-057 Q3).

**Problem**: The alert fired on no data, not on size. `raw-data` walks every tree
of every snapshot, so its cost follows the snapshot count, and nodes ship hourly.
The Beelink passed its 600 s budget on 2026-10-04, and in the three days after
that every other node's `stats` went from 17-19 s to 31-36 s while its repository
stayed at 80-170 MB. One unsized node made the fleet sum `null`, and the rule
paged on that for a day before anyone could tell "near the bill" from
"unmeasured". It also measured the wrong quantity: referenced blobs only. Listing
the same repositories on 2026-10-07 found the Beelink storing 256 MB against the
142 MB `stats` last reported. The difference is unreferenced packs, index and
snapshot files, which the object store keeps and bills.

**Solution**: The watcher's init container lists each bucket at its root and each
node's prefix with `rclone size --json` (BACKUP-075), and the probe reports that as
`stored_bytes`. Each listing took 0-1 s, and the whole Job 36 s. The script always
exits 0, so a failed listing yields `null` and never keeps the health probe from
running.

**Rule**: To measure what an object store bills, list its objects. A tool's logical
view (referenced data, a deduplicated size) costs work proportional to its history
and leaves out the store's own overhead. And a check that grows with history needs
a trend watched, not a timeout raised: here the slowest node failed first, and
every other node was on the same curve.

**Tags**: `#restic` `#r2` `#rclone` `#issue-2077`
