---
id: lesson-753-vacuum-into-writes-rollback-journal-mode
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, sqlite, restic]
---

# `VACUUM INTO` writes a rollback-journal database, even from a WAL one

**Context**: #3053. beelink's `gitea.db` was about half free pages, and the capture's `.backup` copied them into every snapshot. The fix compacts the staged copy with `VACUUM INTO` and leaves the live file alone, because a `VACUUM` on the live file holds a read lock for the whole rewrite, and in rollback-journal mode that refuses Gitea's commits.

**Problem**: `.backup` keeps the source's journal mode, and `VACUUM INTO` does not. Measured on the host's SQLite: `.backup` of a WAL database reads `wal`, and `VACUUM INTO` of that copy reads `delete`. A restore would then silently put an application that chose WAL back in rollback-journal mode. That is the mode where a writer's commit refuses readers, the cause of the 2026-09-04 `database is locked` failure.

**Solution**: The capture reads `PRAGMA journal_mode` on the staged copy before compacting. If it was `wal`, it sets WAL again on the compacted file before moving it into place. If compaction fails, the uncompacted copy ships and the capture warns: the step is an optimisation, never a reason to lose a backup. A test with the real `sqlite3` asserts the freelist is 0, `integrity_check` is ok, the rows are unchanged and the mode is still `wal`.

**Rule**: A step that rewrites a database file must hand back the same file the application wrote, journal mode included. Compare the header-level settings (`journal_mode`, `page_size`, `auto_vacuum`) before and after, not only the rows.

**Tags**: `#sqlite` `#vacuum` `#backup` `#issue-3053`
