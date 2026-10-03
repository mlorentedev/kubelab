---
id: lesson-515-a-sqlite-journal-mode-is-read-from-the-file-header-when-the-image-ships-no-sqlite3
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, sqlite, wal, crowdsec]
---

# A SQLite journal mode can be read from the file header when the image ships no `sqlite3`

**Context**: CrowdSec's database (`kubelab/crowdsec-db`) became a node-backup source in
BACKUP-046. `tests/test_sqlite_sources_are_wal.py` makes every new SQLite source state
its measured journal mode before it may join the set (lesson-427), because `sqlite3
.backup` competes with the writer unless the database is in WAL.

**Problem**: the usual measurement, `PRAGMA journal_mode`, needs a `sqlite3` binary next
to the file, and `crowdsecurity/crowdsec:v1.7.6` ships none. The source was recorded
as `delete` (rollback journal), and in that mode a writer's commit takes an exclusive
lock that refuses readers. The hourly capture then depended on its own timeout and
retries, the same exposure that failed Gitea's capture on 2026-09-04.

**Solution**: read the mode from the file itself. Bytes 18 and 19 of a SQLite header are
the write and read format versions: `1 1` means rollback journal, `2 2` means WAL.
Measured `1 1` before #2002 and `2 2` after it, with `crowdsec.db-wal` and `-shm` present.
The change itself is the image's own knob, `USE_WAL=true` in the base, so both overlays
get it. The image's start script re-applies `db_config.use_wal` on every start, which
matters because the config lives on a PVC that a hand edit would not survive. The
Deployment is `strategy: Recreate`, so two pods never open the file during the switch.
`test_crowdsec_declares_wal` reads the rendered overlay, not the base.

**Rule**: when the tool you would measure with is not in the image, the format usually
answers the question by itself. For SQLite, the header says the journal mode without
opening the database. Declare WAL through the application's own setting that is applied
at every start, not by editing a config stored on the volume.

**Tags**: `#sqlite` `#wal` `#crowdsec` `#node-backup` `#pr-2002` `#issue-1984`
