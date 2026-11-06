---
id: lesson-715-a-generated-pr-must-be-written-on-the-tip-and-only-forward
type: lesson
status: active
created: "2026-11-05"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, deploy-merge, github-actions]
---

# A generated PR must be written on the branch tip, and that checkout alone lets an older build write a downgrade

**Context**: `staging-deploy.yml` builds api for every push to master that touches `apps/api/**`, then
its `open-pr` job promotes the build and force-updates the long-lived `deploy/staging-api` PR (#1681).
deploy-merge merges that PR without a human when its diff is a clean version move (DELIVERY-004, #1619).

**Problem**: `actions/checkout` with no `ref:` checks out the event's sha. On a push, that is the pushed
commit, and it is minutes old by the time the build ends. #3120 merged a bump of the same line during
that window, so #3122, written onto 1b5e724, conflicted with master. A re-run would have conflicted the
same way, because it checks out the same sha.

Checking out `master` fixes the conflict but opens a second hole. The concurrency group orders jobs by
when their build finished, not by push order. An older build can therefore reach the job after a newer
one has merged. On master's tip its promotion is a clean, conflict-free downgrade, which is exactly the
shape deploy-merge merges unattended.

**Solution**: the job checks out `ref: master` with `fetch-depth: 0`. The promote step reads the current
pin (`toolkit deployment image-tag`) and promotes only if `git merge-base --is-ancestor <pin> $GITHUB_SHA`.
Exit 1 (the pin is newer) ends the step cleanly. Any other exit code fails the job, since a pin git
cannot place is not something to guess about. `tests/test_staging_deploy_forward_only.py` runs the
shipped step against a real history.

**Rule**: a job that writes a PR from a long build writes it on the base branch's tip, not the event sha.
When the PR can merge without a human, the same job also refuses to move backwards. The tip checkout
removes the conflict that used to stop an out-of-order write, so it needs that guard.

**Tags**: `#deploy-merge` `#github-actions` `#issue-3122` `#issue-1681`
