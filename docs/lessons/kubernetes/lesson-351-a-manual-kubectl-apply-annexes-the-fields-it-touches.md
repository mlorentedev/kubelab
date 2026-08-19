---
id: lesson-351-a-manual-kubectl-apply-annexes-the-fields-it-touches
type: lesson
status: active
created: "2026-08-19"
owner: manu
category: kubernetes
tags: [kubernetes, gitops, argocd, server-side-apply, drift]
---

# A manual `kubectl apply` annexes the fields it touches, and the bill arrives months later

**Context**: The prod PVC backup had not run since 2026-08-14 — four consecutive
`DeadlineExceeded` failures, found by chance while measuring something else. No
alert existed; `overlays/prod/backup.yaml` has `failedJobsHistoryLimit` and no
notification.

**Problem**: Three separate things were true at once, and each made the others
invisible.

The job's pod was never *scheduled*: `FailedScheduling — persistentvolumeclaim
"gitea-data" not found`. It sat `Pending` until `activeDeadlineSeconds: 1800`
killed it, which surfaces as `DeadlineExceeded` — the same symptom a network hang
produces. Gitea had moved to the Beelink (#1062, 2026-08-14), taking its PVC with
it, on the exact day of the last successful run.

**The manifest was fixed in that same PR. The cluster never got it.**

```
$ kubectl kustomize infra/k8s/overlays/prod | yq -r 'select(.kind=="CronJob" and .metadata.name=="pvc-backup") | .spec.jobTemplate.spec.template.spec.volumes[].name'
authelia-data
n8n-data
tmp

$ kubectl get cronjob pvc-backup -n kubelab -o jsonpath='{.spec.jobTemplate.spec.template.spec.volumes[*].name}'
gitea-data authelia-data n8n-data tmp
```

And Argo CD — `selfHeal: true`, tracking this object, no `ignoreDifferences`, no
`resource.exclusions` — reported `Synced`. The field managers say why, one row
per manager summarised out of that JSON:

```
$ kubectl get cronjob pvc-backup -n kubelab -o json --show-managed-fields
kubelab-toolkit             op=Apply    2026-08-16   owns gitea-data: False
kubectl-client-side-apply   op=Update   2026-05-26   owns gitea-data: TRUE
argocd-controller           op=Update   2026-08-16   owns gitea-data: False
```

A manual `kubectl apply` in May owned that entry. **Under server-side apply a
manager can only remove fields it owns**, so the toolkit and Argo both wrote the
correct volume set, neither was permitted to delete the stale one, and both
reported success. Argo's `Synced` was never a lie — it is accurate about what
Argo controls and silent about what it does not, which is worse, because the fix
is not "make Argo honest".

The trap inside the trap: **the pipeline already used `--force-conflicts` and it
does not cover this.** `toolkit/cli/infra.py` applies with `--server-side
--force-conflicts --field-manager=kubelab-toolkit`, and its comment anticipates
pre-SSA history conflicting "by design". That reasoning is right about the case
it names. `--force-conflicts` takes ownership of fields you **declare**; a field
you do not declare raises no conflict to force, so it survives every apply
until someone removes that ownership deliberately. Migrating to SSA did not
close this — it inherited it.

**Solution**: Delete the object and let the declarative pipeline own it fresh.
`selfHeal` recreated the CronJob in 5 seconds with a single field manager
(`argocd-controller`), the volumes matching the render, and the backup green on
the next run. Safe *here* because no Job was running and the retained history is
disposable — deletion cascades to a CronJob's Jobs and their Pods, so the same
move mid-backup would have killed the run it was trying to rescue. **Not** safe
for a Service with an allocated `clusterIP`, a PVC, or a Secret.

Then the sweep, because one object is never the answer to this question:

```
namespace kubelab: 104 objects scanned
  carrying kubectl-client-side-apply:  81  (78%)
```

Oldest writes from 2026-03-24. The 23 clean ones name the cure without meaning
to: hash-suffixed ConfigMaps that get a new name every deploy, workloads created
after the SSA migration, and the CronJob that had just been recreated. **This is
historical residue, not carelessness** — nobody has run a manual apply since May.

**Rule**: One `kubectl apply` from a laptop annexes every field it writes, and
holds them until someone takes that ownership back by hand. The cost is deferred
until some later change tries to *remove* one of them. Until then nothing
drifts, nothing alerts, and every pipeline reports success. So:

- The risk concentrates wherever a manifest **shrinks**. Adding a field can
  still collide with a foreign manager, but it collides *loudly* — a conflict
  `--force-conflicts` then resolves. Removing one is the operation that fails
  silently.
- `--force-conflicts` is not a cure for pre-SSA history. It resolves conflicts on
  declared fields and is blind to undeclared ones.
- `kubectl get -o json` **hides `managedFields`** since v1.21. Ownership questions
  need `--show-managed-fields`, and without it the answer looks like "no data"
  rather than "not shown".
- When a removal does not take effect, read ownership before theorising. Three
  plausible causes were proposed here — stale controller cache, list-merge
  normalisation, and `last-applied` semantics — and all three were wrong. One
  command settled it.

**Tags**: `#kubernetes` `#gitops` `#argocd` `#ssa` `#issue-1163` `#issue-1164`
