---
id: lesson-486-a-run-the-jobs-if-skips-still-cancels-the-run-that-would-have-reviewed
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, concurrency, pr-agent]
---

# A run the job's `if:` skips still cancels the run that would have reviewed

**Context**: PR #1942 followed the draft-while-iterating standing order: push to a draft, then mark it ready. `.github/workflows/pr-agent.yml` has a workflow-level `concurrency` group keyed on the workflow, the PR number and the event name, with `cancel-in-progress: true`. Its `review` job has an `if:` that skips drafts, Dependabot, forks and `release-please--`, `deploy/` and `promote/` branches.

**Problem**: the PR ended with no review, and its run history read cancelled plus skipped. On 2026-09-30 a force-push to the draft (06:14:22Z) and `gh pr ready` (06:14:36Z) produced two `pull_request` runs, created about 90 seconds apart and in an order unrelated to the events:

```text
36677361269  ready_for_review payload  -> cancelled
36677486394  draft payload             -> skipped
```

Both runs share one concurrency group, so the later one cancelled the earlier one. GitHub resolves concurrency when a run is queued, before any job `if:` is evaluated. The run that lost had the payload that would have reviewed. The run that won had a draft payload, so its `review` job was skipped. A skipped run does no work, yet it still displaced the run that would have.

**Solution**: recovery was a manual rerun of the cancelled run. The fix is tracked in #1944 (TOOL-091). The group must not let a run cancel another unless that run could do work, so `cancel-in-progress` takes the same predicate as the job:

```yaml
cancel-in-progress: ${{ github.event_name != 'pull_request' || github.event.pull_request.draft == false }}
```

**Rule**:

- **The predicate that decides whether a run does work must also decide whether it may cancel.** A `cancel-in-progress: true` next to a job-level `if:` gives a run that will skip the power to cancel a run that will not.
- **The standing order to push to a draft and then mark it ready produces this sequence every time.** Until #1944 lands, a PR that went draft to ready and shows cancelled plus skipped was not reviewed. Rerun the cancelled run.
- **This refines lesson-353 and does not contradict it.** That lesson holds that `cancel-in-progress` is right for a reviewer, because a newer run has strictly newer information. A skipped run has none, so it must not count as newer.

**Tags**: `#github-actions` `#concurrency` `#pr-agent` `#draft` `#pr-1942` `#issue-1944` `#tool-091`
