---
id: lesson-433-a-branch-that-only-improves-a-message-is-invisible-to-a-test-that-asserts-only-failure
type: lesson
status: active
created: "2026-09-05"
owner: manu
category: process-method
tags: [kubelab, process-method, verification, mutation-testing, app-config-004]
---

# A branch that only improves a message is invisible to a test that asserts only failure

> Number: 430 and 431 are claimed by #1648, 432 by a parallel session. Taken as 433
> after checking both, because announcing a number is not allocating one (#1334).

**Date:** 2026-09-05
**Context:** #503 / PR #1661 — `ensure_webhook`'s post-condition
**Category:** process-method

## What happened

`ensure_webhook` writes a repository webhook, then re-reads it and refuses the run
if it did not converge. It has two refusal branches:

```python
live = find_declared_hook(configurator.list_hooks(...), declared)
if live is None:
    raise WebhookError(f"{change.full_name} has no webhook pointing at {declared.url} ...")
remaining = webhook_changes(live, declared)
if remaining:
    raise WebhookError(f"... was written and did not converge — {detail}")
```

Both were covered by a test. Mutation testing killed seven mutants and left one
alive: replacing `if live is None:` with `if False:` kept **every test green**.

The reason is that the branches are not independent. When `live is None`,
`webhook_changes(None, declared)` returns the full field list, so `remaining` is
non-empty and the *second* branch raises anyway. The first branch is redundant for
**failing**. It exists only for its **message** — "the hook was created against a
different URL, or something removed it" is a different investigation from "these
five fields disagree".

And the test asserted `not report.ok`. Which both branches satisfy.

## The general shape

**A test that asserts only that something failed cannot distinguish which failure
it got.** Where two branches produce the same verdict and differ only in
diagnosis, such a test covers the pair and neither one individually. The weaker
branch can be deleted, inverted or mis-wired and nothing goes red.

This is the same family as the class that ran through this whole week — a check
confirming a weaker claim than it appears to (lessons 425, 428, and #1565's guard
over an empty set) — but the mechanism is specific enough to state on its own: the
*assertion* is on the verdict, while the *value* of the code under test is in the
explanation attached to it.

It is easy to miss precisely because the branch looks defensive. Nobody reviews a
`if live is None: raise` and asks whether it is reachable in a way that matters;
it reads as belt-and-braces. The mutation is what asks.

## What to do instead

**When a branch's whole purpose is its diagnostic, assert the diagnostic.**

```python
message = next(msg for target, msg in report.failures if target == "hook personal/resume")
assert "has no webhook pointing at" in message
```

The rule generalises: if removing a branch does not change any assertion, either
the branch is dead — delete it — or the assertion is too coarse. Deciding which is
the work; leaving it undecided is how a code path nothing tests survives review.

## How to notice it without mutation testing

Two tells, both cheap:

- A `raise` whose condition is implied by a later check. Redundant guards are
  usually there for their message.
- A test whose only assertion is a boolean the code has several ways to produce
  (`not ok`, `pytest.raises(SomeError)` with no `match=`). `pytest.raises` without
  `match` is the common form, and it is exactly as coarse as `not report.ok`.

An earlier fix in this same module made the opposite mistake and was caught the
same way: `test_an_absent_settings_block_is_refused_rather_than_defaulted`
asserted `"repository_settings" in str(exc.value)`, a substring **both** the
absent branch and the missing-fields branch print. It survived its mutation until
the assertion named text only one branch emits.

## Related

- [[lesson-416]] — a guard-the-guard belongs on the last value before the
  assertion, never on an input to it. Same discipline, one layer down.
- [[lesson-423]] — a fake cannot verify a request; assert what leaves the process.
- [[lesson-425]] — a probe that measures a single target measures that target's
  history.
