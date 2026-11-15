---
id: lesson-758-a-run-s-duration-mixes-waiting-with-running
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, gitea, actions, diagnosis]
---

# A CI run's duration mixes waiting with running, so read its jobs before blaming a timeout

**Context**: #3079 recorded an openkm-brain job that "hung for 1,675 min while holding one of the two slots" on the Beelink runner. The fix planned for it was a lower runner timeout. The issue had already found that both the runner timeout and Gitea's endless-task bound (3 h each) should have stopped such a job, and neither had.

**Problem**: No bound had failed. Run 810's jobs, read from `GET /repos/{o}/{r}/actions/runs/{id}/jobs`, showed three `windows-latest` jobs with `runner_id` 0 and `started_at` 1970-01-01. No runner carries that label, so no runner ever took them. A job that waits holds no slot, and the runner, endless and zombie bounds never apply to it. Gitea's abandoned-job bound (24 h, checked every 6 h) cancelled them 27.9 h after the run started, as declared. The run's 1,674.8 min was waiting time, and only the job fields could show that.

**Solution**: `make gitea-jobs ENV=prod REPO=<owner/name> [RUN=<id>]` (#1637). It reads a run's jobs and prints each job's runner and running time, or `never started`. Without `RUN` it lists the latest runs, each with its longest job's running time and how many of its jobs never started. Gitea 1.27.3 reports an unset `started_at` as the Unix epoch, and older versions as `0001-01-01`. The reader treats both as never started.

**Rule**: Before you tune a timeout for a "stuck" CI run, read which of its jobs a runner took. A job that never started can mean a `runs-on` label no runner matches (the #1076 shape, as here), a dependency that never finished, or a runner that was busy or off. Check the labels against the registered runners and the job's `needs` before you rule out a hang. Lowering a timeout changes nothing for a job that never started.

**Tags**: `#gitea` `#actions` `#issue-3079` `#issue-1637`
