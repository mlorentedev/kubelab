---
id: lesson-564-a-history-keyed-by-serial-holds-only-if-a-restore-moves-the-serial-forward
type: lesson
status: active
created: "2026-10-13"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, terraform, r2, state, tf-007]
---

# A history keyed by serial holds only if a restore moves the serial forward

**Context**: TF-007 moved every Terraform root's state to R2 (ADR-069). R2 has no
object versioning, so the runner copies the state to
`history/<root>/<lineage>/<serial>.tfstate` before and after every write, with a
create-only PUT (`If-None-Match: *`), under a 365-day bucket lock. A put that finds
its key already taken is treated as "same state, already copied", on the premise
that Terraform never reuses a lineage and serial for different content.

**Problem**: The obvious restore, `terraform state push -force <old copy>`, breaks
that premise. The pushed file keeps its own serial, so the backend's next serial,
or the old serial itself, names content different from the copy already filed
under it. The after-snapshot then meets a taken key and reports success without
copying anything. The restored state would be the one state history does not
hold, and the next apply would land on a serial whose history copy is someone
else's. Nothing would fail; the gap would show only on the day that copy was
needed. `-force` would also replace a different lineage without a word.

**Solution**: A restore is written as a revert, never as a rewind. The runner
fetches the copy, checks that its content carries the lineage and serial its key
names, and sets its serial to the current one plus one. It then pushes without
`-force` and refuses a copy of another lineage. Serials stay monotonic, every
restored state gets a fresh history key, and the state it replaced was already
copied before the write. Mutation-tested: `restored = old`, which restores at the
old serial, turns the restore test red (`make tf-state-restore`,
`tests/test_terraform_runner.py`).

"Key taken" has two spellings in R2. Once a history key falls under the lock
rule, a create-only PUT on it answers `ObjectLockedByBucketPolicy`, not
`PreconditionFailed`: R2 checks the lock before the condition (measured
2026-10-13, when a re-run of a migration met its own earlier copy). The runner
reads both as "already copied", which holds because only the history prefix is
locked, so a locked key is always an existing copy.

**Rule**: When an immutable store is keyed by a version counter and "key exists"
is read as "already stored", every writer must move the counter forward,
restores included. A restore that reuses an old version number turns the
idempotence check into a silent skip.

**Tags**: `#terraform` `#r2` `#state` `#tf-007`
