---
id: lesson-475-repointing-a-shared-preview-slot-without-reading-it-clobbers-another-lane
type: lesson
status: active
created: "2026-09-25"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, staging, parallel-lanes]
---

# Repointing a shared preview slot without reading it first clobbers another lane

**Context**: OPS-023 PR 1 (#1788) had to be validated in staging. Lesson-256's
workaround for Argo CD reverting worktree deploys is to point the staging
Application's `targetRevision` at the feature branch:
`make argo-set-revision APP=kubelab-staging REV=<branch>`.

**Problem**: On 2026-09-25 at about 02:31Z, staging was deliberately on
`fix/grafana-oauth-single-door`, #1825's lane, mid-validation. The command
repointed it anyway. It printed the old value
(`fix/grafana-oauth-single-door → feat/ops-023-retire-minio`) only **after**
the patch. Argo CD synced within seconds and rolled Grafana onto a config
without #1825's change. It rolled again about 90 s later, when the repoint was
reverted. The other lane's validation window was silently invalidated. The
information needed to avoid it was already in the command's own output, one
line too late.

`targetRevision` on the staging Application is **one slot shared by every
lane**. Lesson-256 made that slot the standard way to validate, which turned it
into a contended resource with no lock and no owner.

**Solution**: `toolkit infra argo set-revision` refuses when the current
`targetRevision` is neither `master` nor the requested revision. It names the
holder and exits non-zero. `FORCE=1` (`--force`) overrides it. Pointing back at
`master` is never refused, because that is the patch-back after a merge.
`tests/test_argo_manager.py::TestSetRevisionRefusesAnApplicationAnotherLaneHolds`
pins the refused case, the forced case and the three unheld cases. A mutation
that disables the check turns the suite red. A read-then-patch guard still
races: two lanes that read `master` in the same second both pass it. So the
patch carries the read's `metadata.resourceVersion`, and Kubernetes turns the
second one into a 409 (measured on k3s v1.34.4 with the `Application` CRD: without the version, the same patch overwrote silently). A 409 alone does not name a lane, because Argo CD's
controller bumps the version with every status write. So the command reads
again and lets the guard decide: a status write is retried once, and a real
repoint is refused with its holder's name
(`TestSetRevisionPatchesOnlyTheRevisionItRead`). The Make target forces only on
`FORCE=1`: `$(if $(FORCE),...)` tests emptiness, so `FORCE=0` used to force.

**Rule**: Before writing to a slot other sessions also write to, read it, and
refuse on a value you did not expect. Printing the old value after overwriting
it is an audit log, not a guard. The value to check against is not "empty"
but "the default": a shared slot at its default is free, and any other value
is someone's.

**Tags**: `#argocd` `#staging` `#parallel-lanes` `#issue-1083` `#pr-1788`
