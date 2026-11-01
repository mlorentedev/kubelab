---
id: lesson-682-a-commit-that-changes-only-a-hook-starts-no-sync-so-the-hook-never-runs
type: lesson
status: active
created: "2026-11-01"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, hooks, verification]
---

# A commit that changes only an Argo CD hook starts no sync, so the hook never runs

**Context**: GITOPS-003 AC3 (#1478, #2899) adds a `PostSync` Job that probes web's `/api` route after every sync. To prove the failure path in staging, the probe's path was pointed at `/` in a commit to the held branch.

**Problem**: Nothing happened. The commit (`01240c5`) touched only the hook Job, and Argo CD leaves hooks out of the diff it compares. The Application read `Synced` at the new revision, no operation started, and the hook never ran. Argo CD still posted `argocd/kubelab-staging success "Synced at 01240c5"`, because since lesson-615 the status follows `sync.revision`, not the operation. A broken probe had landed with a green status and had not run once.

**Solution**: Start an operation by hand, `make sync-app APP=kubelab-staging`. The hook then failed (`405 text/html`, read in Loki with `toolkit obs logs --env staging --service route-probe`). The Application's `retry: {limit: 5}` re-ran the whole operation five times, and Argo CD posted `failure` about six minutes after the first failed attempt. The same applied to the revert: it needed its own `sync-app` to run the probe green again.

**Rule**: A hook runs when an operation runs, not when its own manifest changes. To test a change to a hook, start a sync by hand and read the hook's `hookPhase` in `status.operationState.syncResult.resources`; a `success` status on that commit does not show the hook ran. Read the same way, a route probe checks a sync that changed something: a commit that changes no tracked resource is not probed.

**Tags**: `#argocd` `#hooks` `#pr-2899`
