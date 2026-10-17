---
id: lesson-539-a-secret-derived-from-a-declaration-changes-only-when-it-is-re-rendered-not-when-the-declaration-merges
type: lesson
status: active
created: "2026-10-08"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, secrets, argocd, r2, backup-057]
---

# A Secret derived from a config declaration changes when `apply-secrets` re-renders it, not when the declaration merges

**Context**: BACKUP-057's migration sitting moved four nodes into their own R2 buckets and declared them in `backup.r2.own_bucket_nodes` (#2122). The r2-backup-watcher reads two inputs:
- `targets.txt`, which is generated, committed, and synced by Argo CD;
- `r2-backup-watcher-secrets`, whose `RESTIC_PASSWORD_<NODE>` holds each declared node's own password and an undeclared node's shared one (`k8s_secrets.py`).

**Problem**: After the merge, Argo CD synced the new targets and the watcher reached all five buckets (`reachable:1`). It read only ace2. The other four answered `Fatal: wrong password or no key found`, because the Secret still held the shared password for them. Secrets live in git as placeholders and get their values only from `make apply-secrets`, so a merge changes which value a Secret *should* hold without changing the one it does hold. The runbook said "the merge clears it", which was true only for the ConfigMap half.

**Solution**: `make apply-secrets ENV=prod DRY_RUN=1` from a clean master checkout listed `r2-backup-watcher-secrets` as the only change. The apply followed, and the next `make watcher-run` reported 5 of 5 healthy. The runbook's migration section now names the step.

**Rule**: When a config declaration selects which SOPS value a Secret carries, the change has two landing steps: the merge, and an `apply-secrets` from the merged tree. List both wherever the change is described. Run the secrets apply from a clean checkout of master, not from a working tree that holds someone's uncommitted SOPS edit or a branch that is not merged yet.

Related: lesson-455 (a Secret that lands is not a Secret that is read), lesson-538 (the same sitting's copy lock).

**Tags**: `#secrets` `#argocd` `#backup-057` `#r2`
