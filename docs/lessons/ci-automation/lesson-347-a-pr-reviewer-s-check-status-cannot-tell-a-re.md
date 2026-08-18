---
id: lesson-347-a-pr-reviewer-s-check-status-cannot-tell-a-re
type: lesson
status: active
created: "2026-08-15"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation]
---

# A PR reviewer's check status cannot tell a review from a notice, and its inline comments are only a subset of its findings

**Context:** Triaging CodeRabbit on kubelab PR #1098 (archiving the SEC-004 spec), on a plan with one included review at a time and three worktree lanes opening PRs the same evening.
**Problem:** Two independent ways to lose reviewer findings, both of which produce a green PR and neither of which announces itself.

1. When CodeRabbit is out of quota it posts "Review limit reached" and reports that as a PASSING check: `CodeRabbit  pass  0  Review rate limited`. A notice that no review ran is indistinguishable in the status column from a review that found nothing. On #1098 the first pass was a real review and the incremental pass on the fix commit was rate limited — same PR, same green tick, opposite meanings.

2. CodeRabbit does not post all findings inline. Some land only inside the review body under a collapsed "Comments failed to post (N)" section. On #1098, 2 of 4 actionable findings were there, and one of those two was the only Major in the set. A triage reading `gh api repos/{o}/{r}/pulls/{n}/comments` — the obvious endpoint — would have silently dropped it while appearing complete. CodeRabbit names the cause itself, in a CAUTION block: "Inline review comments failed to post. This is likely due to GitHub's internal server error or limits when posting large numbers of comments." So it is a routine volume/transport failure, not an edge case.

3. That CAUTION arrives as a SEPARATE review object, 17 seconds after the one carrying the findings. Both are `state: COMMENTED` from the same author, and the notice sorts last. So `--jq '.reviews[-1].body'` — the obvious way to "read the latest review" — returns the notice and misses every finding. Read ALL review objects, not the last.

The shared root: the reviewer's *transport* is lossy in ways its *summary surfaces* do not reflect, so any triage keyed on status or on the inline endpoint under-reports without erroring.

**Solution:** Tell a review from a notice by CONTENT, never by author or check colour: a review names files, lines, or claims; a notice talks about the review itself. Read every review body — `gh pr view N --json reviews --jq '.reviews[].body'`, never `.reviews[-1]` — and treat the inline comment set as a SUBSET of them, grepping for "Comments failed to post" before concluding the triage is complete. Findings and the notice that findings went missing are different review objects, and the notice sorts last.

When the tip commit is unreviewed because of a quota wall, disclose it rather than letting the green check imply review. Merging unreviewed is defensible; merging while silently appearing reviewed is not.

Operational corollary on a one-review-at-a-time plan: opening a PR consumes the account-wide slot for the whole window, so parallel lanes opening PRs close together means all but one go unreviewed. The window is stamped in the limit notice itself ("next review available in N minutes"); coordinate re-triggers (`@coderabbitai review`) around it instead of assuming per-PR quota.

Second-half credit: the failed-to-post half was surfaced by the parallel fleet-hardening lane after its own PR hit the wall.

**Tags:** `#code-review` `#coderabbit` `#pr-triage` `#ci` `#gotcha` `#verification`
