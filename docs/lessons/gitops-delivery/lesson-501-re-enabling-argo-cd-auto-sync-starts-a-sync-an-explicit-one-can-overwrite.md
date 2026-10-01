---
id: lesson-501-re-enabling-argo-cd-auto-sync-starts-a-sync-an-explicit-one-can-overwrite
type: lesson
status: active
created: "2026-10-01"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, staging, backup, issue-1998]
---

# Re-enabling Argo CD auto-sync starts a sync by itself, and an explicit one sent after it can overwrite it

**Context**: BACKUP-070 (#1998) added `make restore-window`, which pauses an
Argo CD Application's auto-sync (`spec.syncPolicy.automated.enabled: false`),
scales a Deployment to zero for a data restore, and on `END=1` restores the
declared sync policy and asks Argo CD for one sync so the Deployment returns to
git's replica count.

**Problem**: the close step re-enabled auto-sync and then wrote an explicit
`operation` to the Application. On staging, 2026-10-01, the sync history showed
the sync that brought n8n back was `initiatedBy {'automated': True}` at
`eba28e55`, not ours: git had moved since the last sync, so re-enabling
`automated` started a sync on its own, in the same second. An `operation` field
written after that is a plain field write. It does not queue behind a pending
operation; it replaces it, and a sync already Running can be overwritten
mid-flight. The first live run passed by timing, not by construction.

**Solution**: the close builds its sync patch from the same read it patches
under (`resourceVersion` precondition, one retry on 409):

- if the Application already carries an `operation`, or
  `status.operationState.phase` is `Running`, send nothing and wait for that
  sync;
- otherwise send `{"operation": {"initiatedBy": {"username":
  "restore-window"}, "sync": {"revision": <targetRevision>}}}`.

`test_a_sync_argo_cd_already_started_is_not_overwritten` and
`test_a_running_operation_is_not_overwritten_either` cover both branches, and
removing the guard turns them red. The second live run recorded
`initiatedBy {'automated': True, 'username': 'restore-window'}`: Argo CD folded
both into one operation.

**Rule**: after changing an Application's sync policy, **read before you write
an `operation`**. The policy change itself can start a sync, so an explicit
sync is only safe as a conditional write: no `operation`, no Running phase, and
the same `resourceVersion` you read.

**Tags**: `#argocd` `#restore-window` `#issue-1998`
