---
id: lesson-750-git-add-all-from-a-directory-that-no-longer-exists-stages-its-deletion
type: lesson
status: active
created: "2026-11-14"
owner: manu
category: process-method
tags: [kubelab, process-method, git, worktrees, agents]
---

# `git add -A && git commit` from a worktree that has vanished records its disappearance as a mass deletion

**Context**: An agent working on #3443 committed and pushed from a linked worktree in one chained command (`cd <worktree> && git add -A && git commit && git push`). Agent shells reset their working directory between calls, and the worktree directory had been removed underneath the session.

**Problem**: The commit that came out (dc392139) recorded the deletion of the tree rather than the change that was meant. Nothing in the chain asks whether the directory is the one it was meant to be: `git add -A` stages whatever the index and the directory disagree about, and a directory that is missing or emptied disagrees about everything. The push was the step that could have made it permanent. It was checked afterwards that the commit existed on no remote branch and on no other ref, so it did not reach origin, but the chain had no step that would have stopped it had the branch existed there.

**Solution**: The commit was found by reading the log before anything else ran, confirmed absent from origin and every ref, and left unreferenced. The work resumed in an intact worktree.

**Rule**: Before `git add -A`, and always before a push in the same command, prove the cwd is the intended worktree and that the tree is what you think it is: `test "$(git rev-parse --show-toplevel)" = <absolute worktree path> && git diff --cached --stat` and read the stat. A stat that shows hundreds of deletions is the signal to stop. Prefer `git add <named paths>` to `-A`, and keep commit and push as separate calls, so that a look at the commit sits between them.

**Tags**: `#git` `#worktrees` `#pr-3443`
