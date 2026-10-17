---
id: lesson-553-a-slash-command-runs-the-default-branchs-workflow-not-the-prs
type: lesson
status: active
created: "2026-10-10"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, pr-agent, review-attestation]
---

# A slash command runs the default branch's workflow, not the PR's

**Context**: TOOL-021's AC9 asks for the reviewer's own failure to be shown red on a real PR. #2178 broke the reviewer on purpose: push 1 pointed `OPENAI__API_BASE` at a name that never resolves, and push 2 replaced `OPENAI__KEY` with a placeholder. Each edit was to `.github/workflows/pr-agent.yml` on the PR branch.

**Problem**: push 2's `pull_request` run was cancelled while it waited in the shared review queue (#2179). A `/review` comment was posted to run it again. That run succeeded, and PR-Agent published a full review of a PR whose workflow held an invalid key. The run's `headSha` was `41f21b99`, master's head, and its branch was `master`. An `issue_comment` event always runs the workflow file from the default branch, with the default branch's secrets, whatever PR the comment is on. The comment did not re-run the injected workflow. It ran master's, which held the real key.

`pr-agent.yml` says "the workflow file is read from the PR head, so the model travels here too". That is true only for `pull_request` runs. A slash-command run of the same PR reviews with master's model and settings.

**Solution**: the credential half of AC9 moved to a fresh PR with no prior review, and it was triggered by `pull_request` only. A slash command can re-run a review. It cannot exercise a change to the reviewer's workflow.

**Rule**:

- **To test a change to a workflow, trigger it with an event that reads the PR's copy.** `pull_request` reads the PR head. `issue_comment` and `workflow_run` read the default branch, and `pull_request_target` reads the PR's base branch, which here is master. A re-run through any of those three tests master.
- **A review produced by a slash command used master's model and prompt**, even when the PR changes them. Read a review of such a PR by the event that produced it.
- **This is also why the slash-command path is safe on a public repository**: a stranger's PR cannot change what a comment-triggered run executes. The author-association check guards only who may spend the budget.

**Tags**: `#github-actions` `#issue-comment` `#pr-agent` `#tool-021` `#pr-2178` `#issue-2171`
