---
id: "kubelab-runbook-resume-daily-pipeline"
type: runbook
status: active
tags: [runbook, kubelab, resume, cronjob, alerting]
created: "2026-11-17"
owner: manu
---
# resume's daily pipeline

> resume runs `resume daily` once a day as the CronJob `resume-daily`, rendered from
> its contract snapshot (`infra/config/products/contracts/resume.yaml`). Staging only
> for now (RES-HOST-001, #2366). The first deploy and its acceptance steps are added
> here by slice J.

## No-success alert

The rule `reshost001-resume-daily-no-success` fires when no `daily: ok` line from
resume's daily Job reached Loki in the last 26 hours. `resume daily` prints that
line last, on stderr, and only when it exits 0. In staging the alert archives
(`apprise-log`) and never pages.

1. Read the last runs:
   `{container="daily", pod=~"resume-daily-.+"}` over the last two days in Grafana
   Explore. A failed run prints `daily: started <time>` and then names its step:
   `daily: <step> failed`, or `daily: evaluate failed (<reason>)`.
2. No lines at all means no Job reached its container. Read the CronJob and its
   Jobs with `kubectl -n kubelab get cronjob resume-daily` and
   `kubectl -n kubelab get jobs -l app.kubernetes.io/name=resume`, then the pod's
   events: an image pull refused (the `pull-ghcr-io` Secret), or a missing
   `resume-secrets` key, stops it before it logs.
3. A step that failed: fix the cause, then let the next scheduled run clear the
   alert. A finished Job is kept for a day (`ttlSecondsAfterFinished`).

A run is never replayed by hand to silence the alert: the next scheduled run is the
check, and a manual Job is an acceptance step of the first deploy only.
