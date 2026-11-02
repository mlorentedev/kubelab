---
id: lesson-611-an-application-on-apptree-cannot-name-its-degraded-resource
type: lesson
status: active
created: "2026-10-21"
owner: manu
category: gitops-delivery
tags: [kubelab, gitops-delivery, argocd, health, cronjob]
---

# An Application on `appTree` cannot name its Degraded resource, and a retained failed Job never degrades it

**Context**: `kubelab-staging` had been `Degraded` since 2026-10-20T20:29Z.
The first diagnosis (#2580) blamed the watcher CronJobs' retained failed
Jobs. A `disk-watcher` Job had failed at 20:25Z, and failed Jobs as old as 56
days were still listed. The proposed fix was a `ttlSecondsAfterFinished` on
every watcher.

**Problem**: The diagnosis was wrong, and nothing in the Application object
could have shown that. Since Argo CD 2.x an Application can carry
`status.resourceHealthSource: appTree`. In that mode per-resource health lives
in the controller's resource tree, not in `status.resources`. Every entry read
with `kubectl get application -o json` then has `health: null`, so the
object reports `Degraded` without naming a culprit. The failed Jobs were what
you could see, so they got the blame.

Neither half of that blame holds:

- The hub overrides CronJob health. `infra/helm/argocd/values.yaml` sets
  `resource.customizations.health.batch_CronJob` to always return `Healthy`,
  which replaces upstream's last-execution rule
  (`resource_customizations/batch/CronJob/health.lua` at v3.4.1). A CronJob
  here cannot be `Degraded` at all.
- `resource.customizations.health.batch_Job` grades a Job `Degraded` once it
  has a failure. But a Job created by a CronJob is a child in the resource
  tree, not a managed resource. Argo CD computes the Application's health from
  managed resources only, so a failed Job colours its node in the UI and never
  the Application.

On 2026-10-21 the single managed workload failing was the `vikunja`
Deployment, with `Available=False` and `ProgressDeadlineExceeded` (#1783).
The three CronJobs had also succeeded at their last runs: every
`lastSuccessfulTime` was at or after its `lastScheduleTime`.

**Solution**: To diagnose a `Degraded` Application on `appTree`, read the
managed kinds on the spoke and apply Argo's own health rule to each. Do not
guess from what the Application lists. The toolkit already has read helpers
for this: `cronjob_run.get_cronjob` for each CronJob's `lastScheduleTime` and
`lastSuccessfulTime`, and `_run_kubectl get deploy` for the Deployment
`Available`/`Progressing` conditions. Before proposing a fix, read the
health rule that actually applies. Check this repo's
`resource.customizations.health.*` first, then upstream's
`resource_customizations/<group>/<kind>/health.lua` at the hub's version.
Also check whether the kind is managed at all. That, not a plausible story
about history limits, is what decides health.

**Related**: lesson-609 (Application health is deliberately not a condition of
`make verify-product`), #2580, #1783.
