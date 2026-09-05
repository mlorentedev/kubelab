---
id: lesson-429-the-state-that-was-evidence-became-residue-with-no-event
type: lesson
status: active
created: "2026-09-04"
owner: manu
category: observability
tags: [kubelab, observability, verification, alerting, drills]
---

# A verification that creates a condition has no natural end

**Context**: `obs015-pvc-unbound-failure` can only be proven to work by creating
the thing it watches — an unbindable PersistentVolumeClaim. On 2026-08-25 a
drill created `ac2-drill-unbound` for exactly that. On 2026-08-26 `050d2465`
(#1467) fixed the rule's keying. On 2026-08-27 03:29 the alert began firing, and
it was still firing ten days later.

**Problem**: Two separate failures, and neither is the one it looks like.

**The claim was never forgotten.** At the moment the drill succeeded, the PVC
was not rubbish — it was the *evidence*. Deleting it would have destroyed what
was being demonstrated. And no later moment announced itself either: a created
condition goes on being true, so the state passes from evidence to residue with
**no event marking the transition**. There is no instant at which a careful
person looks at it and thinks "this is done now". That is why a teardown step
placed after the observation fails: it is scheduled against a moment that never
arrives.

**And the alert that reported it was correct.** This is the expensive half.
#1467 was a *fix*, it worked immediately, and its entire visible output was an
alert arriving in a channel that had spent months teaching everyone those
alerts were noise. Measured at the time of writing:

```
staging   framesLength=10   one series healthy=0   FIRING
prod      framesLength=8    all healthy            quiet
```

`noDataState: Alerting` fires only on **no** data; ten frames came back. Nothing
about the rule was ambiguous. What was ambiguous was its summary, written
(#1377) to avoid asserting a cause it could not know:

> *Either a PVC is not 'Bound', **or the disk-watcher stopped reporting** — this
> rule alerts on no data too.*

Hedging beats asserting the wrong cause. But it moves the discrimination to the
reader, and **the reader takes the cheap branch**: "the homelab is off" was
available, plausible, and required no action. The alert supplied its own excuse.

**Solution**: bound the state's lifetime by the verification's, and give the
alert the discriminator it already has.

- `make drill-pvc-unbound` creates the claim, waits for the alert, and removes
  the claim **in a `finally` in the same call**. Not a `down` target, not a
  runbook line — those are reminders, and lesson-365 already records that a
  reminder fails exactly when the situation arrives. Ctrl-C at minute twenty
  still removes it.
- Idempotent both ways: the claim is deleted *before* it is created, so an
  earlier run's leftover is absorbed rather than collided with, and the delete
  carries `--ignore-not-found`. That is what let the existing residue be cleared
  by the drill itself instead of by a hand-run `kubectl delete` — the teardown
  path's first real use was against the exact object it exists to remove.
- A failed teardown **raises**; it is not logged. Residue left behind is the
  defect itself, and reducing it to a log line under a more interesting
  exception reproduces the incident.
- Two mutations prove the tests are not decorative: teardown-on-success-only
  fails three tests, teardown-outside-`finally` fails the two that model an
  interrupted operator.

**Rule**: **Ask of any verification: what does this leave behind, and what event
removes it?** If the answer to the second is "someone runs the cleanup
afterwards", there is no such event — a created condition never stops being
true, so nothing will prompt them. The teardown has to be in the same call as
the assertion, or it is a wish.

The second rule is about the channel, not the code: **an alert that names two
causes lets the reader pick the cheap one.** The instance already carried
`namespace` and `pvc` labels — the discriminator existed and never reached the
message. A correct alert whose text supplies its own dismissal is worse than a
wrong one, because the wrong one eventually gets investigated.

Related, and deliberately not the same as
[lesson-428](../process-method/lesson-428-a-check-that-reported-on-a-frame-nobody-had-stated.md):
there the defect is *inside the check*, which measured a sample and reported a
property of the population. Here the check was right after #1467 and the reader
failed. Folding this into that one would widen its claim to "checks can mislead
you", which matches everything — and 428 is the lesson about expectations that
match everything.

**Tags**: `#alerting` `#verification` `#drills` `#issue-1583` `#issue-1467`
`#pr-1645`
