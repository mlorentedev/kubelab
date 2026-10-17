---
id: lesson-323-a-default-value-has-to-be-judged-by-what-it-c
type: lesson
status: active
created: "2026-08-13"
owner: manu
category: observability
tags: [kubelab, observability]
---

# A default value has to be judged by what it converges toward, not just whether it avoids a crash

**Context:** #912 — mute the Apprise/Slack notification on Uptime Kuma's 9 staging-tagged monitors, since the always-on rpi3 prober watches on-demand homelab targets that are correctly DOWN whenever the homelab is off, and alerting on that trains the operator to ignore the dashboard. The fix compares "does the live monitor have a notification attached" against "does the seed, given its tags, want one" and edits when they disagree.

**The trap:** the natural signature for that comparison takes a `has_default_notification: bool` — true when the instance actually has a notification marked `isDefault`. The first draft defaulted the "false" branch to *"the seed wants zero notifications"*, on the reasoning that an instance with no default notification has nothing to attach, so nothing should be requested. That reasoning is correct for the create path — a brand-new monitor genuinely gets no notification — but wrong for the *comparison*: on an instance whose one real notification happens not to carry `isDefault: true` (a plausible SOPS/config drift, not a hypothetical), `has_default_notification` reads `False` even though every one of the 22 non-staging monitors already carries a real, working notification link. Comparing against "wants zero" would flag all 22 as dirty, and the next apply would edit every one of them to an empty `notificationIDList` — silently wiping live alerting across prod, on an unattended sync path, in the name of a monitor-muting feature.

**Fix:** when there is nothing to converge toward, *skip the comparison entirely* rather than picking a value for it. `has_default_notification=False` now short-circuits `_needs_edit`'s notification check before it runs at all, so an edit triggered by an unrelated field never touches whatever `notificationIDList` the instance already has. The same principle was applied to the write side: `edit_monitor()`'s wrapper does `data = get_monitor(id); data.update(kwargs)` before sending — reading its source confirmed that *omitting* a kwarg preserves the live value, which is what "skip" actually relies on to be safe.

**Rule:**
- **A boolean gate on a comparison has three real states, not two: "true", "false", and "not applicable" — collapsing the third into "false" picks an answer for a question that shouldn't be asked.** The tell is asking what the false branch converges *toward*: if the answer is "a state that could wipe something real", the gate needs to skip, not decide.
- **Before trusting a partial-update API to "leave the rest alone", read the source for how it builds the write payload** — not just its docstring. `edit_monitor(id, **kwargs)`'s merge-then-send behavior was the deciding fact for whether "send fewer fields" is actually safe, and it isn't documented, only implemented.
- **Fail-safe (skip, do nothing) beats fail-destructive (converge to empty) on any unattended sync path**, same principle #962/#925 already established for `bootstrap`'s delegation to `apply_monitors` — this is the third time a "the safe default is obviously X" instinct turned out backwards on this exact codepath.

**Tags:** `#uptime-kuma` `#defaults` `#ssot` `#mon-002` `#gotcha`

---
