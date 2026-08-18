---
id: lesson-162-sqlite-backup-requires-sqlite3-backup-api-tar
type: lesson
status: active
created: "2026-03-22"
owner: manu
tags: [kubelab, lesson, sqlite, backup, data-integrity, adr-024]
---

# SQLite backup requires sqlite3 .backup API — tar alone risks corruption

**Context:** Designing PVC backup strategy (ADR-024) for Gitea and Authelia SQLite databases.

**Problem:** Running `tar` on a SQLite database file while the application is writing produces a potentially corrupted backup. SQLite uses WAL (Write-Ahead Logging) mode — the `.db`, `.db-wal`, and `.db-shm` files must be consistent. A tar snapshot can capture them at different points in time.

**Solution:** Use `sqlite3 /path/to/db.sqlite3 ".backup /backup/db.sqlite3"` which uses SQLite's built-in backup API. This creates an application-consistent snapshot even while writes are happening. The CronJob runs `sqlite3 .backup` BEFORE `tar` to get clean copies.

**Rule:** NEVER backup SQLite files by copying/tarring them directly. Always use `sqlite3 .backup` for consistent snapshots. This applies to: Gitea, Authelia, Uptime Kuma, any service using SQLite.
**Tags:** `#sqlite` `#backup` `#data-integrity` `#adr-024`
