---
id: lesson-503-the-highest-surviving-id-cannot-date-a-missing-row
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, sqlite, restore-drill, authelia]
---

# A restore's highest surviving id cannot date a missing row; its `sqlite_sequence` can

**Context**: The BACKUP-068 drill checks that every row live had at snapshot time
came back in the restore. Rows with a creation timestamp are dated by it. Authelia's
`user_opaque_identifier` and `user_preferences` have no timestamp, so the drill
treated a live id above the restore's highest id as "newer than the snapshot".

**Problem**: A restore that lost its trailing rows lowers its own highest id. With
live holding `{1..5}` and the restore `{1..4}`, row 5 read as newer and the drill
passed. The check excused exactly the loss it exists to catch. Restoring an older
snapshot has the same shape. The independent review of BACKUP-068 found it (#2015);
no test covered it, because every fixture lost a row in the middle.

**Solution**: Date a missing row by the restore's own `sqlite_sequence`, the highest
id the database had ever allocated when it was captured. A live id above it was
allocated later, so it is newer. A missing id at or below it existed at snapshot
time and was lost. With `AUTOINCREMENT` an id is never reused, so live still having
it means it was never deleted. Both Authelia tables are `AUTOINCREMENT` in 4.39.15
(migration V0007). Where the sequence is absent, nothing excuses a missing row.

**Why**: "Above the highest" is a property of what survived, and survival is what
the check is measuring. A bound has to come from something the loss cannot change.
The sequence is a separate row in a separate table, written at allocation time.
