---
id: lesson-706-latest-run-of-an-on-status-workflow-is-noise
type: lesson
status: active
created: "2026-11-04"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github, deploy-merge]
---

# The latest run of an `on: status` workflow is almost never its verdict

**Context**: #3062 F11 decided that deploy-merge (DELIVERY-004, #1619) pauses every unattended merge while "the latest
completed deploy-verify run on master" is not green.

**Problem**: `on: status` cannot be filtered by context. Every commit status anywhere in the repository (review-attestation,
pr-agent, deploy-shape) starts a deploy-verify run whose only job is skipped by its `if:`. A run whose jobs all skipped
concludes `success`. The last 100 completed master runs were all `success`. Read literally, a red run is buried within
minutes by the next unrelated status, so the pause would last one status interval, not until staging is fixed.

**Solution**: `pause_reason` in `toolkit/features/deploy_merge.py` walks the runs newest first, reads each run's jobs,
and takes the first run with a job that did not skip as the verdict. A run with no jobs at all (a startup failure)
counts as a verdict too. It fails closed: an unreadable run or job list, or no such run in the page, pauses.
Reading jobs needs `actions: read` on the token, without which the read fails closed and pauses every merge.

**Rule**: before keying on "the latest run" of a workflow, ask what starts it. When a trigger cannot be filtered
(`status`, `check_run`, `workflow_run` on a busy workflow), the run list is mostly skipped jobs concluding `success`.
The verdict is the latest run whose job actually ran.

**Tags**: `#deploy-verify` `#deploy-merge` `#issue-3062`
