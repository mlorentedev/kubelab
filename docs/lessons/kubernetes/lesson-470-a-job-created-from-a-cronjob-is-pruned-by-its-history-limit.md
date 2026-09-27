---
id: lesson-470-a-job-created-from-a-cronjob-is-pruned-by-its-history-limit
type: lesson
status: active
created: "2026-09-27"
owner: manu
category: kubernetes
tags: [kubelab, kubernetes, cronjob, loki, backup-055]
---

# A Job created from a CronJob is pruned by that CronJob's history limit, pod and log included

**Context**: BACKUP-055's staging validation ran four mutation Jobs at once with `kubectl create job --from=cronjob/r2-backup-watcher`, each expected to fail, and read their verdict lines from Loki.

**Problem**: `--from` sets an owner reference to the CronJob, so the CronJob controller adopts the Job and counts it against `failedJobsHistoryLimit: 3`. With four failed Jobs, the controller deleted the oldest one and its pod within about a minute, before Vector had read the container log. That Job's line never reached Loki, and nothing reported that it had been dropped.

**Solution**: read a throwaway Job's output with `kubectl logs job/<name>` as soon as it finishes, or run fewer failing Jobs at once than the history limit allows. Evidence in `specs/archive/BACKUP-055-r2-watcher-probe/verification.md`, Task 10. A manual-run target that captures the log before pruning is #1858 (TOOL-084).

**Rule**: a manual Job made from a CronJob is not yours to keep. It follows the CronJob's history limits, so more concurrent failures than `failedJobsHistoryLimit` lose the oldest one's logs. Capture the output before you start the next run.

**Tags**: `#cronjob` `#loki` `#backup-055` `#1858`
