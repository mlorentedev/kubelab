---
id: lesson-436-a-failed-call-is-not-a-refused-one
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, idempotence, rollback, review]
---

# A failed call is not a refused one, so a rollback needs a reconciliation

**Context**: #1660 fixes a step that pushed a staging branch and then opened the
pull request offering it. Six runs had failed between the two, leaving the branch
orphaned, so the fix deletes the branch when the create fails — undo your own
push, leave no half-applied state.

**Problem**: Review caught what the measurement could not. A non-zero exit from
`gh api -X POST .../pulls` says the **call** failed. It does not say GitHub
refused the request. A timeout, a dropped connection, or a 502 arriving *after*
the pull request was accepted produces exactly the same exit code.

In that case the cleanup deletes the head branch of a **live** pull request.
GitHub closes any PR whose head ref disappears, so the result is a closed PR, a
deleted branch, and a promotion dropped with nothing left to recover it from.
Silently — which makes it strictly worse than the orphan branch being fixed,
because an orphan is loud, recoverable, and (per
[lesson-434](lesson-434-when-every-normal-path-deletes-it-the-residue-is-a-counter.md))
countable.

The rollback was written as if the failure were *at-most-once*. Network calls are
*at-least-once* at best: the effect and the acknowledgement are separate events,
and only the acknowledgement was observed.

**Solution**: Ask what the state actually is before undoing anything, and give
the answer three outcomes rather than two.

```
confirmed no PR exists   -> delete the branch, exit red
a PR exists              -> keep the branch, say so, exit red
the lookup cannot answer -> keep the branch, say so, exit red
```

The third is the one that is easy to omit. The reconciliation query shares the
REST quota with the create, so the exhaustion that broke one can break the other
— and **"cannot tell" must not round to "absent"**. Same shape as this repo's
closing-refs guard, which exits 2 for *unanswerable* precisely so a broken query
never reads as a clean result.

Which way to round is decided by which mistake is recoverable, not by which is
likelier: keeping a branch that should have gone costs a stale ref someone can
delete; deleting one that should have stayed costs a promotion nobody can get
back.

**Rule**: Before writing a compensating action — a delete, a revert, a refund —
ask what the failed call *might have already done*. If the answer is "possibly
succeeded", the compensation must first observe the state, and must decline to
act when it cannot. A rollback that assumes failure means nothing happened is a
second bug wearing the first one's fix.

**Tags**: `#idempotence` `#rollback` `#github-actions` `#pr-1660` `#code-review`
