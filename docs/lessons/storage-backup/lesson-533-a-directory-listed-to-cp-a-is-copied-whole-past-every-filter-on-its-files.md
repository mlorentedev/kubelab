---
id: lesson-533-a-directory-listed-to-cp-a-is-copied-whole-past-every-filter-on-its-files
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, sqlite, find, cp]
---

# A directory listed to `cp -a` is copied whole, past every filter on its files

**Context**: `node-backup-capture.sh.j2` takes a consistent `sqlite3 .backup` of each
source's database, then copies "everything else" with
`find . -mindepth 1 ! -path ./<db> ! -path ./<db>-wal ... -exec cp -a --parents`.
The filters were written for the database file, and the tests asserted they were in
the script.

**Problem**: `find` lists directories as well as files, and `cp -a` copies a directory
recursively. When the database sits in a subdirectory, the filters stop the file but
not its parent: beelink's Gitea is `gitea/gitea.db`, so `./gitea` was listed, copied
whole, and the raw `gitea.db` and its `-wal` landed over the snapshot staged a moment
earlier. Every Gitea snapshot since BACKUP-044 held a raw copy of a live WAL database.
The restore drill passed because Gitea opened it and SQLite replayed the WAL, which
proves the replay worked that time, not that the copy was consistent (#2111). Found
while adding a source whose databases are nested (`cron/executions.db`).

**Solution**: prune the declared paths and copy only non-directories and empty
directories (`\( -path ... \) -prune -o \( ! -type d -o -empty \) -exec cp -a --parents`).
`--parents` with `-a` recreates the directories in between with their modes (measured
700 and 750 kept). The pruned set gained `-journal`: a raw hot journal beside the
snapshot is rolled back into it on open. The new tests render the script and run it
against a tree in `tmp_path`, with a fake `sqlite3` that writes a marker where the
snapshot goes, and assert what the staging directory holds.

**Rule**: a filter on a path is only as good as what the command does with the paths
it lets through. When the consumer recurses (`cp -a`, `tar`, `rsync` without `-d`), an
exclusion on a file means nothing once its directory gets through. Test a copy step by
running it on a tree and reading the result. A string assertion on the filters cannot
see this.

**Tags**: `#sqlite` `#backup-integrity` `#find`
