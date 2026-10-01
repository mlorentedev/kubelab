---
id: lesson-495-a-backup-exclusion-with-a-trigger-is-a-promise-nobody-keeps
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, postgres, vikunja, coverage, guard]
---

# A backup exclusion with a trigger is a promise nobody keeps; only a tier is a ruling

**Context**: On 2026-10-01 the operator asked whether restarting Vikunja could lose the board. Its tasks live in prod Postgres (`kubelab/postgres-data`), and that claim had no backup.

**Problem**: `common.yaml` excluded Postgres on 2026-08-22 with a reason that was true that day: "measured empty (0 tables) … It joins this list the day something writes to it." Vikunja started writing five days later. #1111 recorded that on 2026-09-03, with live evidence, and proposed the fix. Nothing changed for another four weeks, because nothing executes a sentence. The exclusion read as a reasoned decision to everyone who checked coverage, and the only guard in the repo (`tests/test_backup_volume_coverage.py`) covered Docker volumes on one node, not PVCs. The data survived because nothing broke, not because anything protected it.

**Solution**: BACKUP-046 (#1111). An emergency `pg_dumpall` was taken first and restored into a scratch container, where row counts matched live. Then:

- Postgres is a source with a `pg_dumpall` capture method that refuses a dump without its completion trailer.
- Every prod claim the overlay renders must be ruled on, in `backup.sources` or in `backup.excluded`, and every exclusion must carry `tier: 3` with a reason. `tests/test_backup_pvc_coverage.py` enforces both, and it failed on master with five unruled claims.
- The live half, for claims created outside the manifests (`kube-system/traefik`), goes in `make backup-coverage`.

**Rule**: when you exclude state from backup, write down a classification that stays true by itself ("tier 3: rebuilt from git"), never a condition that someone has to notice changing ("until something writes to it"). If the honest answer is "not yet", back it up now: an empty database costs nothing to dump. Make the ruling exhaustive over something a test can enumerate, so new state fails CI instead of waiting to be noticed. A ticket comment is a reminder, and reminders fail exactly when the situation arrives.

**Tags**: `#backup` `#postgres` `#vikunja` `#coverage` `#issue-1111`
