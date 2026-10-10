---
id: lesson-554-a-staging-secret-applied-from-a-branch-outlives-its-merge
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, secrets, staging, backup]
---

# A staging Secret applied from a branch outlives its merge, because Argo CD reverts the branch's manifests but never its Secrets

**Context**: While auditing OBS-007, `make test-infra ENV=staging` reported three Failed `r2-backup-watcher` pods. Loki showed every staging run on 2026-10-09 and 2026-10-10 reading 4 of 5 node repositories as `Fatal: wrong password or no key found`. Over the same window, prod's watcher read 5/5 healthy against the same buckets.

**Problem**: Both envs build `r2-backup-watcher-secrets` from the same SOPS keys in `common.enc.yaml`, yet the live Secrets differed: 4 restic passwords did not match. These values were compared by hash and never printed. The staging Secret had been written on 2026-10-07T16:45Z. It already carried `RESTIC_PASSWORD_ACE2`, a key master gained only when #2115 merged at 21:32Z. So it was applied from a branch before the merge. Four of its passwords differed from prod's live Secret, and the vps one matched no master commit since 2026-10-03, so the branch's SOPS carried at least one value master never held. `apply-secrets` writes Secrets outside git, so Argo CD neither tracks nor reverts them. A branch preview's manifests are undone by the next sync (lesson-330, #1083), but its Secrets stay until someone re-applies, and nothing re-applies. The result was three days of a broken staging watcher, found by accident.

**Solution**: `make apply-secrets ENV=staging` from master. Exactly one Secret reported `configured` and every other one `unchanged`, so the drift was confined to that Secret. Then `make watcher-run NAME=r2-backup-watcher ENV=staging` read `"unhealthy":0` for 5 nodes. The class, and the cleanup of the Failed pods that outlive the fix, are #2194.

**Rule**: Returning staging to master means returning its Secrets too. A branch preview that ran `apply-secrets` is not over when `targetRevision` points back at `master`; it is over when `apply-secrets --env staging --dry-run` from master reports nothing `configured`. To tell a staging Secret's drift from a code bug, compare hashes of the live keys against the other env, never the values.

**Tags**: `#secrets` `#staging` `#issue-2194` `#lesson-330`
