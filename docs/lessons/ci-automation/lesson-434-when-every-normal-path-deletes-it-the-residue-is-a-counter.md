---
id: lesson-434-when-every-normal-path-deletes-it-the-residue-is-a-counter
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, rate-limits, measurement, web]
---

# When every normal path deletes it, the leftovers are a counter

**Context**: Six `deploy/staging-web-sha-*` branches sat on the remote against one
open staging PR. It read as untidiness — a cleanup job nobody had written — and
was first written up that way, as a side effect of the per-sha branch scheme in
#1645.

**Problem**: The tidiness reading was wrong, and it was hiding a defect that had
been running for ten weeks.

Two settings delete these branches, from opposite directions:

- the repository sets `delete_branch_on_merge: true`, so a **merged** staging
  branch is removed by GitHub;
- the receiver's coalescing step closes superseded PRs with
  `gh pr close --delete-branch`, and has since #784, so a **superseded** one is
  removed by CI.

Between them, every ordinary end of a staging branch's life deletes it. Which
means a surviving branch is not litter — it is *evidence*, and the only thing it
can be evidence of is a branch that never had a pull request at all. Checked:

```
3cf83f3 -> NO PR EVER      d914178 -> NO PR EVER
238bc41 -> NO PR EVER      f042c77 -> NO PR EVER
4329aeb -> NO PR EVER
```

Five for five. The count of orphan branches *is* the count of staging promotions
that were computed, committed, pushed — and then offered to nobody. Following
that back through the run history:

| | |
|---|---|
| Runs of `Web Image Receiver` | 119 |
| Failures | 6 |
| In the step `Open staging deploy PR` | **6 of 6** |
| Distinct causes | **1** — `GraphQL: API rate limit already exceeded` |
| Earliest | **2026-06-28** |

**Solution**: #1660 — open the PR over REST (a separate quota bucket from
GraphQL) and delete the pushed branch when the create fails, so the failure
leaves no half-applied state.

But the lesson is the reading, not the fix. I had attributed this to myself: two
expensive `gh project item-list` calls exhausted the account-wide GraphQL budget
that night and broke the receiver, which is true and is
[lesson-039 in `web`](https://github.com/mlorentedev/web). Having caused *an*
instance, I wrote up *the class* as mine. The branch count is what showed there
were five more, the first ten weeks earlier, with no agent anywhere near them.

**Rule**: Before dismissing residue as untidiness, ask what would have had to
happen for it to *survive*. Where every normal path removes a thing, what remains
enumerates the abnormal ones — and an enumeration is a measurement, available for
free, with no instrumentation to add and no logs to retain.

This is also the cheapest correction for a bias worth naming: **the incident you
caused is not evidence that you are the cause of the class.** A recent, vivid,
self-inflicted example crowds out the question of how long the thing has been
happening. Count the residue before accepting the story.

**Tags**: `#measurement` `#github-actions` `#rate-limits` `#pr-1660` `#issue-1651`
