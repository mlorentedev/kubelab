---
id: lesson-608-synced-at-head-is-read-from-sync-revision-not-from-the-last-operation
type: lesson
status: active
created: "2026-10-20"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, verification, sync]
---

# "Synced at HEAD" is read from `sync.revision`, not from the last operation's revision

**Context**: GITOPS-003 (#1478) needed a check that a promotion is live:
`make verify-product APP=web ENV=staging` reads `kubelab-<env>` from the hub
and asks whether it is at `origin/master` HEAD before reading what the product
serves. The obvious field is `status.operationState.syncResult.revision`: the
commit the last sync applied.

**Problem**: That field is HEAD only when HEAD changed the env's manifests.
Read on the hub on 2026-10-20 with master at `ed5747f`: both Applications were
`Synced` with `status.sync.revision == ed5747f`, while the last operation of
staging was at `4ab3083` and of prod at `c95d4b9`. A commit that leaves the
overlay unchanged moves `sync.revision` (Argo compared HEAD and found it equal)
and starts no operation, because automated sync acts only on `OutOfSync`. A
check keyed on the operation's revision is red after nearly every merge, and a
check that is usually red is soon ignored.

The two fields answer two questions. `sync.status` + `sync.revision` say
whether the live state equals HEAD. `operationState` says whether the last
attempt worked, at whatever revision it ran. Its revision matters in one case:
a `Failed`/`Error` operation AT HEAD is final, because Argo makes one automated
attempt per revision (lesson-407). A failure at an older revision is not this
merge's verdict yet.

Also measured the same day: `status.health` of `kubelab-staging` was `Degraded`
because of failed `disk-watcher`/`r2-backup-watcher` Jobs and a Vikunja pod
stuck in init, none of them the product being verified. Application-wide health
as a condition would have blocked every staging verification.

**Solution**: `toolkit/features/product_verify.py:classify_application`:
ready = `sync.status == Synced and sync.revision == HEAD and
operationState.phase == Succeeded`; failed at once = phase in `Failed`/`Error`
and the operation's revision is HEAD; anything else waits until the deadline.
The product's own health is judged by what its host serves (`/version.json`),
not by the Application. Mutation-tested with `make mutate`: dropping the
`sync.revision == head` clause turns 3 tests red.

**Rule**: To ask "is the cluster at commit X", compare `sync.revision`; to ask
"did the attempt fail", read `operationState`, and treat a failure as final only
when its revision is X. Never use a field because its name sounds right: read
the live object at a commit that did not touch the manifests first.

**Tags**: `#argocd` `#gitops-003` `#issue-1478`
