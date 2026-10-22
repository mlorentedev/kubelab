---
id: lesson-615-a-status-keyed-on-the-sync-operation-misses-every-no-op-revision
type: lesson
status: active
created: "2026-10-21"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, notifications, verification]
---

# A commit status keyed on the sync operation misses every revision whose render does not change

**Context**: GITOPS-003 (#1478) PR1 made Argo CD post a commit status
`argocd/kubelab-<env>` per sync, through a trigger on
`operationState.phase == 'Succeeded'` with `oncePer` the operation's revision.
PR2 (`deploy-verify.yml`) reads that status for master HEAD, and a scheduled
sweep is red when none arrives within N minutes.

**Problem**: Most commits on master leave an env's render unchanged (docs,
tests, the other env's overlay). Argo compares HEAD, finds it equal, moves
`status.sync.revision` to HEAD and starts no operation, because automated sync
acts only on `OutOfSync` (lesson-609). With no operation, a trigger on the
operation never fires, so those commits get no status. Measured 2026-10-21: the
only `argocd/kubelab-prod` success on master came from a drift-correcting
operation after an Authelia restart, not from a merge. The sweep would have
been red after nearly every merge, the failure lesson-609 warned against, one
layer up.

**Solution**: Two triggers keyed on two different fields. Success
(`trigger.on-synced-github`) fires when `app.status.sync.status == 'Synced'`,
`oncePer: app.status.sync.revision`, and the template posts to
`.app.status.sync.revision`: every revision Argo reports synced gets one
success, operation or not. It is withheld while the last operation is running
or did not succeed (`operationState == nil or phase == 'Succeeded'`): a failed
PostSync hook leaves the app Synced, and a success posted after the failure
would bury it (PR-Agent on #2613). Failure keeps the operation's revision, because a
failed operation is about the commit that operation ran. The success template
reads nothing from `operationState`, so it cannot describe a stale operation.
`tests/test_argocd_notification_triggers.py` holds both shapes.

**Rule**: A per-commit signal must key on the field that changes for every
commit. For Argo CD that is `sync.revision`; `operationState` changes only for
commits that change the render. Before wiring a notification to a check, list
which commits produce no event, and test with one of them.

**Tags**: `#argocd` `#gitops-003` `#issue-1478`
