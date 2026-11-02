---
id: lesson-628-a-copied-snapshot-keeps-its-time-but-a-bucket-lock-ages-it-from-the-copy
type: lesson
status: active
created: "2026-10-26"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, object-lock, retention]
---

# A copied restic snapshot keeps its time, but a bucket lock ages it from the copy

**Context**: BACKUP-057 put each node's restic repository in a bucket of its own, with an R2 lock that refuses any delete younger than R = 30 days. The retention flags were chosen so the two could never collide: `--keep-within 31d` keeps every snapshot younger than R, and `--max-repack-size 0` means a pack is deleted only once wholly unused, so it is older than every snapshot that used it. On 2026-10-07 (#2122) the existing history of vps, rpi3, rpi4 and beelink was moved into the new buckets with `restic copy`.

**Problem**: From then on, `node-backup-prune` failed every day on the migrated nodes. On the VPS, `forget` chose to remove `e390107e` (2026-09-13) and `37757357` (2026-09-20), and R2 answered `The object is locked by the bucket policy` for both: exit 3, and a page. The invariant was right about native history and wrong about copied history. `restic copy` gives a snapshot a new id but keeps its `time`, and writes every object it brings at the moment of the copy. `forget` judges age by `time`, the lock by the object. For R days after the copy, the two disagree by however old the copied history is. Snapshots are refused with exit 3, but packs are refused with exit 0, so only the snapshot half of the conflict was visible.

**Solution**: The prune lists the repository first, lock-free and bounded like the ship's probe. If any snapshot carries `original`, the field `restic copy` stamps on a copy and `unmatched_snapshots()` already reads, `forget` waits until the oldest snapshot without it is older than R. The migration copies before the node's first ship to the new repository, so that snapshot is newer than every copied object. The run logs the date it expects to clear and exits 0. A repository with no copies is never held. `node_backup_r2_lock_retention_days` comes from `backup.r2.lock_retention_days` through the playbook, with no role default. On the migrated nodes the wait ends around 2026-11-07, and the first real prune after that date is the evidence for AC3. The skips before it are not.

**Rule**: Under an object lock, the age that matters is the object's write time, and a tool's notion of age (a snapshot's `time`, a file's mtime, a record's date) is not that once data has been copied, restored or rewritten. When a retention invariant is stated as "keep-X exceeds the lock", list every operation that writes old data new (copy, rewrite, repack, restore into a fresh store) and check the invariant for each.

**Tags**: `#restic` `#r2` `#object-lock` `#backup-057` `#issue-1920`
