---
id: lesson-761-compacting-a-backup-copy-shrinks-what-ships-not-what-is-stored
type: lesson
status: active
created: "2026-11-15"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, sqlite, restic]
---

# Compacting a backup copy shrinks what a snapshot reads, not what restic stores

**Context**: #3053 and #3547. beelink's `gitea.db` was about half free pages, and R2 growth (#3035) looked like it came from them. #3547 compacted the private staged copy with `VACUUM INTO` before each ship and left the live file alone. It ran on beelink from 2026-11-14 20:48 to 2026-11-15 21:30.

**Problem**: The free pages were never what restic stored. Measured on beelink:

- Each snapshot processed about 82 MiB less (the free pages). Back-to-back runs stored 1.1 MiB before and after.
- Timer ships in windows with no Gitea activity stored 1.06 MiB before and 1.11–1.44 MiB after.
- In active windows `restic diff` replaced 159–191 MiB of files before and about 138–157 MiB after, against a 160 MiB compacted database. The in-use pages are rewritten almost entirely either way.

Free pages that do not change already deduplicate between snapshots, so removing them saves reading, not storage. Compaction also renumbers the file's pages, so the first compacted snapshot re-stores the whole file, and going back re-stores it again (17.8 MiB and 33.4 MiB here).

A second finding from the same change: `VACUUM INTO` always writes a rollback-journal database. `.backup` of a WAL database reads `wal`, and `VACUUM INTO` of that copy reads `delete`. A restore from it would put an application that chose WAL back in the mode where a writer refuses readers (the 2026-09-04 `database is locked` failure). #3547 restored the mode before moving the file into place.

**Solution**: #3547 was declined with these numbers, and beelink went back to master's capture (`make backup ENV=prod NODE=beelink`; `changed=1` then `changed=0`, processed back from 402 to 480.7 MiB). The stored bytes come from active windows: the database's in-use pages, Actions logs, packages and repository objects.

**Rule**: Before shrinking a backup's input to cut storage, check what deduplication already removes. Measure the stored bytes (`data_added_packed`) of the scheduled ships across an active window, never the bytes processed or a back-to-back run. A step that rewrites a database file must hand back what the application wrote, journal mode included.

**Tags**: `#sqlite` `#vacuum` `#restic` `#dedup` `#issue-3053`
