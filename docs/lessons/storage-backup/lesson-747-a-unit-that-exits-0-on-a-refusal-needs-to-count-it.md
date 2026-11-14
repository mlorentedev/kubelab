---
id: lesson-747-a-unit-that-exits-0-on-a-refusal-needs-to-count-it
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, observability]
---

# A unit that exits 0 on a refusal has to count it, or "0 failures" means nothing

**Context**: Closing BACKUP-057 AC3, which asks for seven days with no `node-backup-prune.service` failure. `make backup-schedule` reported 0 on every node.

**Problem**: Three different things all read as that 0. A prune that ran `forget` cleanly. A prune that waited for copied history and never called `forget` (#1920). A prune whose pack deletes the bucket lock refused: restic retries for about 15 minutes, logs `unable to remove data/<id> from the repository`, and exits 0. On 2026-11-14 rpi3 and rpi4 were in the third state, every night. And the count covered only what each journal held: 2 runs on rpi3, rpi4 and beelink, because journald keeps 20 MB (#2702).

The first guess at the orphans' origin was the week's ship failures during the edge outages. The ship script rules that out: those failed in the `snapshots --no-lock` probe, which runs before `backup`, so they uploaded nothing.

**Solution**: The prune no longer `exec`s restic. It tees the output and ends every run with `node-backup-prune: N deletes refused by the bucket lock, M failed otherwise`, keeping restic's exit code. `backup-schedule` now prints, per node, how many prune runs the journal holds, how many waited, the last refused count, and how many ships found the repository locked (#3496).

**Rule**: When a unit exits 0 on purpose for an outcome that is not success, print that outcome as a count on its own line and read it next to the failure count. Report the denominator too: a failure count over a journal that kept two runs is not a week. And before blaming a failure for a side effect, check which stage the failure stopped in.

**Tags**: `#restic` `#bucket-lock` `#backup-057` `#issue-3496`
