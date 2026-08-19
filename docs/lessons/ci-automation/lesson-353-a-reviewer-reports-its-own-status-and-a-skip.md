---
id: lesson-353-a-reviewer-reports-its-own-status-and-a-skip
type: lesson
status: active
created: "2026-08-19"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation]
---

# A reviewer reports its own status, and a skipped review is not a failed one

**Context:** building the review-attestation gate (TOOL-021, #1140). Replaying the last 40 merged PRs through the classifier before trusting it gave **32 `declined`, 5 `attested`, 3 `pending`** — 35 of 40 merged with nobody having reviewed them, every one showing a green reviewer check.

**Problem:** two autonomous reviewers ran here, and **both fail open on independent account-wide quotas**. When the quota is spent they post a notice and set their status to **success**. Caught in the act on #1165, two statuses on one commit, nineteen seconds apart:

```
CodeRabbit:          success — "Review limit reached … we couldn't start this review"
review-attestation:  success — "a review happened"
```

The reviewer is reporting on itself. A skipped review is not a failed one, so nothing goes red, and "reviewed" and "not reviewed" render identically.

**Solution:** a check that answers one question — *did a review happen* — from **content**, never from another check's status. Five states, and `declined` (a reviewer said it could not) stays distinct from `pending` (nobody spoke). Anything unreadable exits non-zero: for a gate, "I could not determine" delivered as "fine" is the defect itself.

**Rule:**

- **Never derive a verdict from another tool's check status.** It reports on its own execution, not on the property you care about. Read what it *said*.
- **Tell a review from a notice by content, not by author** — the same account posts both. A review names files, lines or claims; a notice talks about the review itself.
- **Replay history through a new monitor before trusting it.** It cost almost nothing here because the classifier is pure and takes a payload file, and it produced the real denominator *and* refuted a comment written from a four-PR sample.
- **A gate that makes absence visible does not make review available.** Both halves are needed: the check went live before a quota-free reviewer existed, and for an hour every PR was correctly red with no way to clear it. Land the detector and the capacity close together.
- **Publish a commit status, not a check-run.** A check-run belongs to the run that created it and can never be revised, so a later attestation could not clear an earlier red. This matters because `cancel-in-progress` is correct here — a newer run has strictly newer information — and cancellation is the common case once a reviewer speaking is itself a trigger. Note `gh pr checks` renders `cancelled` in its **fail** column; the API reports it accurately.
- **Requiring the wrong name inverts the gate.** The revisable **status** may be required; the **job** may not, because a run cancelled by design can never conclude green.

**Tags:** `#ci` `#review` `#gate` `#gotcha` `#pr-1162`
