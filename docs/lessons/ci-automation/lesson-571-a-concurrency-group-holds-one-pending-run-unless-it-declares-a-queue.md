---
id: lesson-571-a-concurrency-group-holds-one-pending-run-unless-it-declares-a-queue
type: lesson
status: active
created: "2026-10-14"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, pr-agent, concurrency]
---

# A concurrency group holds one pending run unless it declares a queue

**Context**: PR-Agent's `review` job shares one concurrency group across every
PR (`pr-agent-nan-inference`, `cancel-in-progress: false`), so that reviews wait
their turn for NaN's five shared inference slots. The workflow's own comment
had recorded since #1203 that the group did not really queue, and called it
"not solved here". TOOL-108 (#2179) measured the cost.

**Problem**: `cancel-in-progress: false` protects only the run that is already
executing. Without a queue, GitHub keeps one running and ONE pending run per
group, and a newer pending run cancels the older one before it gets a runner,
so no step of it ever runs, not even an `always()` guard. From outside, a
discarded review looks like a review that ran and published nothing.

Measured over the 1,500 `pr-agent` runs from 2026-10-01 to 2026-10-14, 54
cancelled runs never got a runner:
- 36 were cancelled within ten seconds of another PR's run entering the group,
  which is this defect;
- 5 were superseded by a push to the same PR, which is intended;
- 13 had no trigger nearby, most likely manual cancellations or closed PRs.

Meanwhile the operator had serialised pushes by hand, polling `gh run list`. A
three-minute gh 401 made that poller read "idle", and it skipped a push.

**Solution**: `queue: max` on the job's group turns it into a FIFO; dotfiles
had run the same design since 2026-10-01 (mlorentedev/dotfiles#1940). GitHub refuses `queue: max`
beside `cancel-in-progress: true`, so the queue stays on the job and the
workflow-level per-PR group keeps cancelling superseded runs. A queued run
keeps the event it was queued with, so a new first step drops a review whose PR
merged, closed or turned draft while it waited (mlorentedev/dotfiles#2079). actionlint
1.7.12 does not know the key yet, and `.github/actionlint.yaml` ignores exactly
that message for this file.

**Rule**: When a workflow comment says a limit is "not solved here", check the
sibling repositories that run the same workflow before treating it as an open
design question: the fix may already be running next door. And a client-side
serialiser that polls an API should treat an error as "busy", never as "idle".

**Tags**: `#github-actions` `#concurrency` `#pr-agent` `#issue-2179`
