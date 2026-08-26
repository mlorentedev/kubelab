---
id: lesson-401-a-second-commit-on-a-branch-someone-else-can-merge-is-a-bet-you-lose-silently
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: process-method
tags: [kubelab, process-method, git, governance, board]
---

# A second commit on a branch someone else can merge is a bet you lose silently

**Context**: Board-governance work (GOV-004, GOV-005) spanned several small, independent additions — the duplicate-id detector, the priority scale, the priority `--apply` extension — built one after another while the human reviewed and merged PRs in parallel, in the same session.

**Problem**: Twice, a second commit was pushed onto a branch whose first commit's PR the human had just squash-merged. A squash merge snapshots the PR at merge time; a commit that lands after that snapshot is not in the merged result, even though `git push` succeeds and the branch still shows it. First time: `board_ids.py` (a whole feature) went missing from PR #1419, caught only because `gh pr diff --name-only` was checked against the live compare API rather than trusted from the PR's own (stale) metadata. Second time: `toolkit board priority --apply` — code that had already been *run* against the live board, its effect real and persisted on GitHub — sat uncommitted in the working tree because it was written after `--apply`'s own PR (#1430) had merged; caught only by `git status` during the session handoff checklist, not by any active check.

**Solution**: Fetch `origin/master` and diff it against the branch tip before adding a second *unit of work* — not before every commit, and not a substitute for `git status` — to an existing branch (`git diff origin/master HEAD -- <files>` empty means HEAD's own commits are already merged in substance, safe to abandon). This checks committed history only; it says nothing about the working tree, which is exactly why the second incident was still only caught by `git status`, not by this diff. When HEAD is already merged, branch fresh off `origin/master` for the next piece — carrying uncommitted working-tree changes across a `git checkout -b` is safe and keeps every logically separate addition on its own branch, so a merge decision made on branch A can never eat branch A's future.

**Rule**: In any session where a human can merge a PR while you keep working, treat every new commit as a bet that the branch is still open — verify before adding it, don't assume the branch you're on is still "yours" to build on. The check costs one `git diff`; the loss costs a re-diagnosis and a second PR.

**Tags**: `#process` `#git` `#board` `#pr-1419` `#pr-1430` `#pr-1443`
