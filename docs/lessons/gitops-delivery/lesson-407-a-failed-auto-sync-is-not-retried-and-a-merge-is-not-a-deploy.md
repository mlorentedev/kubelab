---
id: lesson-407-a-failed-auto-sync-is-not-retried-and-a-merge-is-not-a-deploy
type: lesson
status: active
created: "2026-08-27"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, sync, notifications, verification]
---

# A failed Argo CD auto-sync is not retried, and a merged manifest is not a deploy

**Context**: #1465 raised the same-origin `/api` route priority (10 → 100) so
the web host's `POST /api/subscribe` would reach the API instead of nginx. It
merged at 06:14Z with green CI, a clean drift gate and a triage that recorded
"post-deploy staging smoke test — out of scope, needs a live cluster". Prod
synced the revision at 06:14:58 and its route worked.

**Problem**: Staging never got it. The automated sync of `1489265` panicked
inside the controller — `controller/sync.go:311`, `WithPermissionValidator`
called with a nil `APIResource` from `gitops-engine sync_context.go:1070` —
after a 30.9 s API-discovery timeout from the hub to `ace1` (88 `i/o timeout`
watch failures on `traefik.io/v1alpha1` at 04:47Z). That is upstream
argoproj/argo-cd#27659, fixed in v3.5.0+; the hub runs chart `9.5.13`, v3.4.1
(#1209). What made it an outage rather than a blip is what Argo did next:

```text
Skipping auto-sync: failed previous sync attempt to [1489265] and will not retry
```

every three minutes, indefinitely. **Argo CD makes one automated attempt per
revision.** A failed sync stays failed until a new commit lands or someone
syncs by hand. The `on-sync-failed` notification reached Slack at 06:17:23Z and
nobody dispositioned it. Thirty-five minutes later the live `IngressRoute`
still said `priority: 10` and staging still answered the site's own 404.

**Solution**: `make fetch-kubeconfig ENV=hub DIRECT=1` (a workstation on the
mesh needs no `ts-bridge` hop), then `make sync-app APP=kubelab-staging` →
`Succeeded` at the first attempt; no `restart-argocd` needed. Verified by
consequence, without mutating anything:

```text
GET  https://staging.mlorente.dev/api/health     -> 404 text/plain   (Gin, not nginx)
POST https://staging.mlorente.dev/api/subscribe  -> 400 text/plain   (malformed body)
```

The guard — the receiver waiting for `Synced` at the merge SHA and probing the
route — is #1478.

**Rule**: A merged manifest is a claim; `Synced` at the merge SHA is the fact,
and only the route answering is the proof. Two things about Argo CD change how
a delivery path must be written: a failed automated sync is *never* retried on
its own, and the notification that says so is only a guard if something
dispositions it. Any workflow that says "promoted" must read
`status.operationState` back and go red when the operation errored or was
skipped — the same lesson as 319 and 406, one layer further down: the manifest
was right, the cluster never heard about it.

**Tags**: `#argocd` `#auto-sync` `#notifications` `#verify-by-consequence` `#pr-1465` `#issue-1478`
