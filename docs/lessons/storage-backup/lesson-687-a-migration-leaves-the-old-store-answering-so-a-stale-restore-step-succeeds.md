---
id: lesson-687-a-migration-leaves-the-old-store-answering-so-a-stale-restore-step-succeeds
type: lesson
status: active
created: "2026-11-01"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, runbook, migration]
---

# A migration leaves the old store answering, so a stale restore step succeeds

**Context**: BACKUP-057 moved every node out of `kubelab-backups` on 2026-10-08. By design the old bucket stayed in place, undeleted, until the new ones had proved themselves. The runbook's restore section was scheduled for the close-out PR.

**Problem**: For more than three weeks the restore steps still read the shared pair and `kubelab-backups/<node>`. Nothing failed, and nothing could: those credentials and that repository still work, so the steps would list snapshots, restore them and report success, with data frozen at the migration. Every check on the pipeline was green, because they all read the new buckets. `backup-verify-destination` and `backup-verify-restic` stayed green for the same reason, proving the abandoned bucket (#2917).

**Solution**: `tests/test_offsite_runbook_claims.py` pins the sections an operator follows to the per-node paths, derived from the toolkit, and the restore was run read-only with the commands the runbook now gives.

**Rule**: Keeping the old store during a migration turns every stale reference to it from a failure into a silent success. Change the recovery documentation in the same sitting as the cutover, not in the close-out, and treat "the old path still works" as the hazard rather than the safety net.

**Tags**: `#restic` `#r2` `#runbook` `#backup-057` `#issue-1920`
