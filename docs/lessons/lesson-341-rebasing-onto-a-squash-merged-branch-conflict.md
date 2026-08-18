---
id: lesson-341-rebasing-onto-a-squash-merged-branch-conflict
type: lesson
status: active
created: "2026-08-16"
owner: manu
tags: [kubelab, lesson, git, squash-merge, rebase, worktrees, gotcha]
---

# Rebasing onto a squash-merged branch conflicts against your own merged work

**Context:** an implementation branch was cut from a spec branch. The spec PR merged, and `git rebase origin/master` on the implementation branch immediately conflicted — on the spec files, against content that was already upstream.

**The trap:** this repo squash-merges, so master received the spec as **one** commit whose content matches the *end state* of the branch's three. Rebase replays those three originals on top of that end state, and each one conflicts with the result it helped produce. The conflict markers look like a genuine disagreement between two authors; they are the branch arguing with its own merged output, and "resolving" them by hand reintroduces intermediate states that were deliberately squashed away.

**Fix:** drop the already-merged commits instead of replaying them. Cut a fresh branch from master and cherry-pick only what is *not* upstream.

```bash
git rebase --abort
git checkout -B <branch> origin/master
git cherry-pick <impl-commit>     # only the commits master does not have
```

**Rule:**
- **After a squash-merge, the parent branch's commits no longer exist upstream in any form git can match.** `git rebase` has nothing to deduplicate against — unlike a merge-commit workflow, where it would drop them silently.
- **Stacked branches and squash-merge do not compose.** Either rebase the child *before* the parent merges, or plan to cherry-pick after. Deciding this at conflict time is how intermediate states leak back into history.
- **A conflict in files your branch did not modify in this commit is the signal.** It means the commit is already applied, not that someone else edited it.

**Tags:** `#git` `#squash-merge` `#rebase` `#worktrees` `#gotcha`
