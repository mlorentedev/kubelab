---
id: lesson-479-a-deploy-that-imports-from-its-worktree-reverts-other-lanes-on-shared-staging
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, staging, n8n, parallel-lanes]
---

# A deploy step that imports from the worktree it runs in reverts every other lane's state on shared staging

**Context**: APP-CONFIG-015 (#1712) and APP-CONFIG-016 (#1871) tested n8n
workflow changes in staging while other lanes validated unrelated changes on
the same cluster.

**Problem**: `make deploy-k8s` ends with `make import-n8n`, which imports the
workflows **from the checkout it runs in** and restarts n8n (#1859). Staging is
one cluster shared by every lane. So a deploy from any other worktree, for a
change that has nothing to do with n8n, silently replaced the branch's
workflows with master's. Measured 2026-09-27 during BACKUP-055's validation.
Nothing reports it: the deploy succeeds, n8n restarts healthy, and the next
probe from the n8n lane measures master's workflow while believing it measures
the branch. The step is also not idempotent (n8n restarted on each of two
consecutive runs), and its failure path is swallowed by `|| echo`.

This is the same shape as the Argo CD resync in CLAUDE.md's staging flow, but a
different mechanism: Argo reapplies tracked manifests when git moves, while this
writes state Argo does not track at all (n8n's workflows live in its database),
so Argo cannot restore it either.

**Solution**: until #1859 decouples the import from `deploy-k8s`:

- import your own state immediately before measuring: `make import-n8n
  ENV=staging` from your branch, then `make n8n-probe ENV=staging`, with nothing
  in between;
- tell the lanes that deploy to staging before you import, and ask them to say
  so before they deploy (the #1712 and #1871 validations were run that way).

**Rule**: on a shared environment, **any deploy step that writes state from
the local checkout is a write into every other lane's test**. Validate
immediately after writing your own state, re-verify live state at the moment
of measurement rather than at deploy time, and treat an implicit import inside
a general-purpose deploy as a defect, not a convenience.

**Tags**: `#staging` `#n8n` `#issue-1859` `#issue-1712` `#issue-1871`
