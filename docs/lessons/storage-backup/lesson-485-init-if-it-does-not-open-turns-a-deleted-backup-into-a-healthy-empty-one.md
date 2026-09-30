---
id: lesson-485-init-if-it-does-not-open-turns-a-deleted-backup-into-a-healthy-empty-one
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, backup-058]
---

# "Initialise it if it does not open" turns a deleted backup repository into a healthy, empty one

**Context**: every node ships its capture to its own restic repository on R2. The ship script opened with `restic snapshots || restic init`, written so a first ship would create the repository without a separate bootstrap step.

**Problem**: that fallback does not distinguish *why* `snapshots` failed. A repository that someone deleted, or that a bucket policy removed, came back on the next run as a new repository holding one snapshot. The R2 watcher checked that the repository opens, holds a snapshot, and contains every source and the capture sentinel. It called the result healthy, and every earlier restore point was gone without a page. A repository *replaced* by another one was worse still: `snapshots` answers 0, so the ship wrote into a history that was not the node's.

**Solution** (BACKUP-058, #1921): gate `init` on restic's exit code and pin identity by the repository id.

- Measured against R2 with restic 0.19.1 on 2026-09-30: a missing repository returns **10**, a wrong password **12**, and an *invalid credential never returns at all*, even with `--stuck-request-timeout 45s` (#1939). `init` now runs only on exit 10, and every other code exits with that code.
- The restic repository id (`restic cat config --json` → `id`) is new on each `init` and never changes otherwise. As soon as its first `backup` succeeds, each node writes it to `/var/lib/node-backup/r2.repository-id`: from then the repository holds a restore point, even if retention fails afterwards. From then on, exit 10 fails loudly instead of initialising, and a different id fails before `backup` writes anything.
- `make backup-repo-reinit NODE=<node> DEST=r2 ENV=<env>` is the only way to start over. It journals the recorded id, then removes the marker.

**Rule**: a create-on-miss fallback in front of stored history must answer *why it missed*, not only *whether*. Read the tool's exit code, measure which failures produce which code against the real backend, and allow creation for exactly one of them. Then pin the identity of what you created: a same-named replacement answers every "does it exist" check with yes.

**Tags**: `#restic` `#r2` `#backup-058` `#1921` `#1939`
