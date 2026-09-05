---
id: lesson-438-a-declared-automation-is-not-an-executed-one
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pre-commit, git-hooks, verification, tool-064]
---

# A declared automation is not an executed one — check the route the failure actually takes

**Context**: #1649. The lesson corpus count is a number written by hand in three
places, and git merges that line as text without raising a conflict. Four
collisions in two days; at one point three open PRs were red on it at once. The
fix was to stop writing the number and derive it, applied by a pre-commit hook —
turning a rule people must remember into a fact that cannot be wrong.

**Problem**: The hook was declared correctly and did not run where it mattered.
Four separate reasons, each found only by trying it rather than reading it —
and the fourth was found by this lesson's own pull request going red:

1. **git does not run `pre-commit` for a merge that resolves cleanly.** The
   hook's own comment claimed it fired on the merge commit. Measured:

   ```console
   $ git merge tmp/merge-probe
   Merge made by the 'ort' strategy.
    docs/lessons/observability/lesson-901-probe.md | 6 ++++++
     (no hook output at all)

   $ ls docs/lessons/*/lesson-*.md | wc -l   ->  433
   $ grep '^[0-9]* lessons' docs/lessons/_index.md   ->  432 lessons
   ```

   The defect walked in by the exact route that caused all four collisions,
   straight past the hook written to stop it.

2. **A `stages: [pre-push]` entry in `.pre-commit-config.yaml` would never have
   executed.** This repo sets `core.hooksPath` to share hooks across worktrees,
   and its `pre-push` is its own script that never invokes `pre-commit`. The
   natural-looking home for the second stage is a file nothing reads.

3. **`core.hooksPath` resolves to the *main* worktree's copy.** Editing
   `.github/hooks/pre-push.sh` in a feature worktree changes nothing for that
   worktree; `readlink -f` on the hook lands in `~/Projects/kubelab/`, and
   `grep -c` for the new check returned `0`. The guard starts protecting when
   the change reaches master, not when it is written.

4. **A branch updated from the GitHub UI runs no local hook of any kind.** The
   "Update branch" button merges master into the PR branch *on GitHub's
   servers*: there is no local commit for `pre-commit` to see and no local push
   for `pre-push` to intercept. Measured on this very PR — `7cc5b6fc`, a
   `Merge branch 'master' into docs/lesson-declared-is-not-executed` authored
   by the button — which brought the corpus to 434 files against a declared
   433 and turned the `Tests` job red on `test_the_real_index_currently_agrees`.

   So `.pre-commit-config.yaml`'s claim that *"nothing reaches CI stale, which
   is the whole point"* is false, and the PR that shipped the two stages proved
   it four hours later. CI is not a redundant net here; on this route it is the
   only one. Two local stages plus a red build is the honest description.

Each of the four is invisible to every test of the *logic*. The reconciler had
15 passing tests and worked perfectly; what did not work was anything reaching
it.

**Solution**: Verify a mechanism by the route the failure takes, not by the
route you had in mind. Two stages, each proven as a live cycle rather than as a
unit test:

```text
commit path -- a lesson arrives, counters untouched
  commit 1 -> hook FAILED, "files were modified by this hook"
              total 432 -> 433, category column 17 -> 18, heading 17 -> 18
  commit 2 -> clean

push path -- simulated post-merge tree, 433 files and 432 declared
  [ERROR] The lesson index counters disagree with the files on disk.
  exit 1
```

The push check lives in the script git actually runs, and a test asserts it is
wired *there* — plus asserts that no `pre-push` stage is declared in the config
file, since that is the plausible-looking mistake.

**Rule**: When you automate away a recurring mistake, name the route the
mistake takes and prove the automation sits on it. "It runs on commit" is a
claim about your workflow, not about the defect: this one arrived by merge, and
merges skip `pre-commit` entirely. Four questions the same shape — *does this
hook run at all, in this repo's configuration, from this working tree, on the
machine where the merge happens?* — and all four answers were no, while the
config read as correct. A mechanism is not verified by its unit tests any more
than [[lesson-429]]'s drill was; run it against the thing it is supposed to
catch, and watch it catch it.

And having enumerated the routes, say which ones you did **not** cover. A
server-side merge is outside the reach of any local hook, so the residual net
is CI and the honest sentence is "two stages and a red build", not "nothing
reaches CI stale". Claiming full coverage is how the next person stops looking.

Corollary for shared hooks: `core.hooksPath` means a hook change is inert until
it lands on the branch the main worktree has checked out. Say so when you ship
one, or the next person will conclude it does not work.

**Tags**: `#pre-commit` `#git-hooks` `#verification` `#pr-1673`
