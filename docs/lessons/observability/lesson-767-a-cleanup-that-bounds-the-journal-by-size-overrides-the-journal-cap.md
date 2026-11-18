---
id: lesson-767-a-cleanup-that-bounds-the-journal-by-size-overrides-the-journal-cap
type: lesson
status: active
created: "2026-11-18"
owner: manu
category: observability
tags: [kubelab, observability, journald, ansible]
---

# A cleanup that bounds the journal by size overrides the journal's own cap

**Context**: #3637 and #3586. `make backup-schedule` reports seven-day counts read from the journal: ship backups begun / saved, prune runs, refused deletes.

**Problem**: On 2026-11-18 it read `4 / 4` for beelink's ships. That missed the ship systemd killed on 2026-11-15, which had begun a backup and saved nothing, so the count should have been `5 / 4`. beelink's journal listed one boot and used 24.0M. journald was configured as designed, `Storage=persistent` and `SystemMaxUse=1G` (`base_system`, #2702 sized 1G for 14 days). But the `node_maintenance` role also ran `journalctl --vacuum-size=20M`, from the timer script and from its tasks. The vacuum predates the cap and was never removed, so the cap never held more than about 20M. The VPS is always on, never rebooted and has the same 1G cap, and it reached back 3.8 days. So reboots were not the cause; the vacuum was.

**Solution**: #3637 removed the vacuum, which leaves `SystemMaxUse` as the journal's one bound. A test fails if the role contains `--vacuum-` again. `backup-schedule` now leads with how far back the whole journal reaches, and says "NOT 7 days" when it reaches less, because the 20M nodes still will.

**Rule**: A size or age bound on shared state belongs to one owner. A second role that trims the same state with its own number silently wins whenever its number is smaller. A count over "the last N days" read from a log has to state the log's actual reach, or a short log reads as a clean week.

**Tags**: `#journald` `#retention` `#backup` `#issue-3637`
