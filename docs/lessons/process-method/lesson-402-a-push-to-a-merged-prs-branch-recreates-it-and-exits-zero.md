---
id: lesson-402-a-push-to-a-merged-prs-branch-recreates-it-and-exits-zero
type: lesson
status: active
created: "2026-08-26"
owner: manu
category: process-method
tags: [kubelab, process-method, git, review, pr]
---

# A push to a merged PR's branch recreates the branch and exits 0

**Context**: pr-agent reviewed #1455 and found a real defect. The fix was written, tested and pushed. In the meantime the PR was merged, which deleted the branch.

**Problem**: The push succeeded. Git created the branch again — it had no reason not to — and reported it in one line among eighteen lines of pre-commit output:

```
 * [new branch]      fix/fetch-kubeconfig-rotated-host-key -> fix/...
```

Exit code 0. No warning, no failing check, nothing on the pull request. The end state is a **merged pull request whose branch has reappeared carrying one unmerged commit**, which nothing in this repository looks at: PR checks run on open PRs, `dotf pr triage-queue` reads reviewer output, and neither has an opinion about a resurrected branch. The fix for a reviewer's finding was, for a few minutes, in no branch anyone would ever merge.

It was caught by reading `* [new branch]` and recognising it as impossible for a branch known to exist. That is not a mechanism; that is luck wearing the costume of vigilance.

**Solution**: Recovered by cherry-picking the orphaned commit onto a fresh branch cut from the new `master` and opening #1460, then deleting the resurrected branch. The disposition was recorded on the merged #1455 rather than quietly, because a triage that arrives after the merge is still a triage and pretending otherwise is the actual failure.

The mechanism is filed as [#1462](https://github.com/mlorentedev/kubelab/issues/1462) and **built on 2026-09-01, after the trap was sprung twice more in a single session** — which is the strongest evidence the lesson alone was never going to be enough: a pre-push guard that asks the forge whether the branch's PR is already merged and refuses the push if so, failing **open** when the forge cannot be reached — a guard that blocks pushes during a GitHub outage trades a rare silent loss for a frequent hard stop.

**Rule**: This is [lesson-401](lesson-401-a-second-commit-on-a-branch-someone-else-can-merge-is-a-bet-you-lose-silently.md)'s family but a different mechanism, and the distinction matters for the fix. 401 is *a second commit dropped by a squash-merge* — the branch exists, the commit is real, the merge ignores it. This one is *the branch no longer existing*, and git silently rebuilding it. A guard for one does not catch the other.

What they share is the shape worth internalising: **a tool reporting success it did not achieve.** `git push` exits 0 having pushed to nowhere that matters. The absence of an error is not evidence of an effect, and on any operation whose success depends on state held somewhere else — a forge, a cluster, another machine — the only honest verification is to ask that other place what it now believes.

And per [lesson-365](lesson-365-a-lesson-with-no-mechanism-is-a-reminder-and-i-broke-mine-three-times.md): this is the third occurrence in this family in two days. Writing a fourth lesson would be the wrong response. The ticket is the response.

It lives in `.github/hooks/pre-push.sh`, inherited by every worktree through
`core.hooksPath`, and it refuses a push that would recreate a branch whose PR is
`MERGED` or `CLOSED`. Verified against real pull requests rather than fixtures,
with the controls that make the refusal mean something: a brand-new branch, an
ordinary update to an existing remote branch, and a branch *deletion* all still
pass silently.

**Tags**: `#git` `#review` `#pr-1455` `#pr-1460` `#issue-1462`
