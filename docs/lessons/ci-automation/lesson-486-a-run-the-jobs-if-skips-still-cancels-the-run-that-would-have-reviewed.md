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

**Solution**: recovery was a manual rerun of the cancelled run. The fix is #1948 (TOOL-091, #1944): the draft flag is part of the workflow-level group key, so a run the job skips lands in a group of its own:

```yaml
group: >-
  ${{ format('{0}-{1}-{2}{3}',
  github.workflow,
  github.event.pull_request.number || github.event.issue.number,
  github.event_name,
  github.event.pull_request.draft && '-draft' || '') }}
cancel-in-progress: true
```

The first design made `cancel-in-progress` conditional on the same predicate as the job. It was dropped because it covers only half the failure: GitHub keeps at most one *pending* run per group, and a new pending run evicts the one waiting whatever `cancel-in-progress` says. A draft run in the same group could still evict a pending review. A separate group cannot. The draft flag is the only skip condition that changes during a PR's life; the others (Dependabot, forks, branch prefixes) are fixed per PR, so every run of such a PR skips alike and none can displace a reviewing run.

**Rule**:

- **The predicate that decides whether a run does work must also decide which group it joins.** A concurrency group next to a job-level `if:` gives a run that will skip the power to cancel, or evict, a run that will not. Key the group on the predicate; a conditional `cancel-in-progress` does not reach eviction.
- **The standing order to push to a draft and then mark it ready can produce this sequence whenever the two runs are created in the wrong order**, which GitHub does not control for. Before #1948, a PR that went from draft to ready and shows cancelled plus skipped was not reviewed: rerun the cancelled run.
- **This refines lesson-353 and does not contradict it.** That lesson holds that `cancel-in-progress` is right for a reviewer, because a newer run has strictly newer information. A skipped run has none, so it must not count as newer.

**Tags**: `#github-actions` `#concurrency` `#pr-agent` `#draft` `#pr-1942` `#issue-1944` `#tool-091`
