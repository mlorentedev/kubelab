---
id: lesson-489-a-rotation-keyed-on-the-iso-week-breaks-once-a-year
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, backup-063]
---

# A rotation keyed on the ISO week breaks its coverage guarantee once a year; key it on epoch weeks

**Context**: BACKUP-063 made the weekly `restic check` read pack data back with `--read-data-subset n/t`. With a deterministic `n`, every pack is read within `t` weeks. The issue proposed deriving `n` from the ISO week.

**Problem**: ISO week numbers run 1 to 52 or 53 and then wrap back to 1. So `week mod t` does not advance by one at the year boundary: it skips groups or repeats one. For example, 2027-01-01 falls in ISO week 53 of 2026. With `t = 4`, weeks 52, 53 and 1 give the groups 0, 1, 1: one group is read twice, and the group it displaced waits a full extra cycle. The guarantee "every pack within `t` weeks" is therefore false once a year, and no test that stays inside one calendar year notices.

**Solution**: count weeks since the Unix epoch, `$(date +%s) / 604800 % t + 1`, which is continuous. The test fixes the clock with a fake `date` on `PATH` and asserts the steps across that boundary: `[1, 1]` under epoch weeks, against `[1, 0]` under the ISO week.

**Also measured**: memory does not grow with how much data the check reads. Read-data streams packs, so a full read on the RPi3 peaked at 78-83M against 76M for the structure-only check. Time does grow, at about 1 pack per second on the RPi3. So when a repository grows, raise `t` because of the unit's timeout, not because of its `MemoryMax`.

**Why it matters**: any "every item within N periods" rotation built on a calendar field that resets inherits this defect: day of year, ISO week, month. Key the rotation on a monotonic counter.
