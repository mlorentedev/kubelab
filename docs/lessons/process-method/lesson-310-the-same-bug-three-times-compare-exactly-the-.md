---
id: lesson-310-the-same-bug-three-times-compare-exactly-the-
type: lesson
status: active
created: "2026-08-11"
owner: manu
category: process-method
tags: [kubelab, process-method]
---

# The same bug three times: compare exactly the fields you write

**Context:** `make monitoring-apply` deleted all 31 Uptime Kuma monitors and recreated them on every run, discarding every monitor's uptime history (#962). The fix was an upsert that compares the seed against the live instance.

**Problem:** The comparison was wrong three times, each more subtly than the last.

1. It projected the two sides onto **different field sets** — `key` stripped from the seed, `active`/`tags`/`notificationIDList` stripped only from the live monitor. Every real monitor therefore read dirty. 16 unit tests passed, because their fixtures carried none of those fields.
2. Fixed by hand-enumerating the exclusions. That held for the three fields I knew about and silently failed for two I did not: `expiryNotification` (in 20 seed entries, in neither the export list nor the API payload) and `httpBodyEncoding: null` (in 11, and the apply path skips `None`). 20 + 11 = the 31 phantom edits.
3. Only the third fix was structural: one `WRITABLE_FIELDS` set that **both** the payload builder and the comparison derive from.

**Solution:** Compare exactly the fields the write path sends, enforced by construction. A field the apply path never writes cannot be reconciled, so flagging it as a difference requests an edit that can never clear the flag — the monitor is not merely noisy, it is *permanently* dirty.

What caught it was not a test. It was running the plan **read-only against the live instance** before ever writing: connect, fetch the real monitors, compute the diff locally, print it. The defect lived in the gap between the real seed and what the write path accepts, and no fixture written by the author of the code was going to contain that gap.

**Rule:**
- **In any declarative sync, the comparison set and the write set must be the same object.** Two lists describing one contract will drift, and the drift is invisible because both halves look correct in isolation.
- **A unit fixture cleaner than production data cannot test the case that matters.** These fixtures carried `{key, name, interval}`; real monitors carry twenty fields. Build at least one fixture from the real artifact.
- **Dry-run against production state before writing to it.** Read-only, no risk, and here it was the single highest-value step of the session — it found a defect that had already passed review and merged.
- **Verifying the absence of damage means checking what the damage would have taken.** The proof that the sync was safe was not that it exited 0; it was that monitor 462 still had 720 beats of history afterwards.
- **A negative control can be invalid in a way that flatters you.** Adding `expiryNotification` to the writable set did *not* reproduce the bug — because the fix makes that field written *and* compared. Reproducing it required breaking the symmetry itself. A control that passes may be testing nothing.

**Tags:** `#declarative-sync` `#uptime-kuma` `#ssot` `#false-negative` `#test-fixtures` `#dry-run` `#negative-control` `#ops-016` `#gotcha`
---
