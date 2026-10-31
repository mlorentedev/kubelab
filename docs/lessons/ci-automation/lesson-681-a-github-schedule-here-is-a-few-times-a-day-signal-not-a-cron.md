---
id: lesson-681-a-github-schedule-here-is-a-few-times-a-day-signal-not-a-cron
type: lesson
status: active
created: "2026-10-31"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, gitops, observability]
---

# A GitHub `schedule` in this repository is a few-times-a-day signal, not a cron

**Context**: GITOPS-003 needed a clock for the case where Argo CD posts no
commit status at all. `deploy-verify.yml` (#2615) got a `schedule` sweep at
`7,37 * * * *` for it: every 30 minutes, check that master HEAD has
`argocd/kubelab-prod` `success`.

**Problem**: GitHub delays scheduled runs under load, and in this repository the delay
is the normal case. `delivery-health` (`0 7 * * *`) and `config-drift`
(`0 6 * * *`) started 4 to 9.5 hours late on every day measured over 10 days
(#2645). The sweep, read on 2026-10-31, ran 40 times in a week, all green, but
3 to 6 hours apart (18:49Z, 22:55Z, 02:16Z), not every 30 minutes. A check
whose job is "within N minutes" cannot live on that trigger: it reports a
missing status hours late, and it looks fine, because the runs that do start
are green.

**Solution**: The clock moved into the cluster (#2645 B), on the watcher
pattern ADR-028 already uses: a `delivery-watcher` CronJob runs every 10
minutes, reads master HEAD and its Argo status anonymously from the GitHub API,
and prints one `argo_delivery` line. A Grafana rule on Loki pages on
`healthy < 1`, including no data. `deploy-verify` keeps what event triggers do
well: `on: status` turns red at once on a failed sync, and `workflow_dispatch`
replays any commit.

**Rule**: Do not put a latency bound on a GitHub `schedule` trigger. Treat it as
"at some point today", read its real cadence from the run history
(`actions/workflows/<file>/runs?event=schedule`) before relying on it, and put
any clock measured in minutes where a scheduler keeps time: a CronJob, a timer,
Uptime Kuma.

**Tags**: `#github-actions` `#gitops` `#pr-2615` `#issue-2645`
