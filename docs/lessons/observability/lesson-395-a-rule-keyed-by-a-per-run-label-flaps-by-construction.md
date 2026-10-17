---
id: lesson-395-a-rule-keyed-by-a-per-run-label-flaps-by-construction
type: lesson
status: active
created: "2026-08-25"
owner: manu
category: observability
tags: [kubelab, observability, grafana, loki, alerting]
---

# A rule keyed by a per-run label flaps by construction

**Context**: Demonstrating AC2 of #1377 — that the PVC alert fires when a PVC really is unbound — after #1404 made the `disk-watcher` CronJob emit a numeric `healthy` again.

**Problem**: Vector labels every Loki stream with `pod` (`infra/k8s/base/services/vector.yaml:84`), and every CronJob run is a new pod. `last_over_time({container="disk-watcher"} | json | unwrap healthy [30m])` therefore yields one series per (pod, pvc): each run creates a fresh alert instance, and the previous run's instances go stale once the 30-minute window passes them. Prod Grafana's log shows it without any drill — `Detected stale state entry`, 8 per evaluation (8 PVCs), every 15 minutes. For a genuinely unbound PVC the cycle is Pending → Alerting → stale/Resolved, restarting with every run: the alert fires, and posts a false Resolved every 15 minutes. `for: 15m` never means fifteen minutes.

**Solution**: Key the instance by what is measured, not by who measured it — `last_over_time(... | unwrap healthy [30m]) by (namespace, pvc)` — so the series survives across runs. The fix is pending on #1377; the finding is what the drill was for.

**Rule**: Before writing an alert over log-derived metrics, list the stream labels the query inherits and aggregate away every one that changes per emitter run. The tell that you did not: a stale-state line on every evaluation, N per run.

**Tags**: `#grafana` `#loki` `#alerting` `#issue-1377`
