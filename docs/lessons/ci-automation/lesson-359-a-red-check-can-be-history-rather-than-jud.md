---
id: lesson-359-a-red-check-can-be-history-rather-than-jud
type: lesson
status: active
created: "2026-08-20"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, review-attestation]
---

# A red check can be history rather than judgement — re-trigger before investigating

**Context**: PR #1187's `review-attestation` status read
`failure — "not reviewed, and not declared as such"` while PR-Agent had already
published its declared `## PR Reviewer Guide` marker on the same PR.

**Problem**: I treated that as a live contradiction — a declared reviewer's
declared marker present, and the classifier refusing anyway — and recorded it on
the ticket as a second, unexplained symptom, deliberately not guessing the cause.

The timeline settles it, and nothing about the classifier was wrong:

| Time (UTC) | Event |
|---|---|
| 07:32:36 | PR-Agent posts `## PR Reviewer Guide` |
| 07:33:14 | gate fires on `issue_comment` |
| **07:24:45** | **the status the PR was displaying** |

The visible red predated the reviewer output by eight minutes. **`gh pr checks`
shows the last status posted, not the current verdict**, and a gate that only
re-evaluates on new reviewer output or a push has no reason to refresh a status
whose inputs it has not been told changed.

The same shape appeared twice more the same day: two of #1187's rows were red
because the branch predated the merges that fixed them (#1188, #1192), and a
rebase cleared both.

**Solution**: Re-trigger, then look. A comment re-fired the gate and it returned
`success — "a review happened"` immediately, closing the ticket's second symptom
as a non-defect.

**Rule**: Before investigating a red check, establish **when it was posted**
relative to the thing it is judging. A status is a record of one evaluation, not a
live view. Two questions answer it: *has anything the gate reads changed since
that timestamp?* and *has the branch since fallen behind a fix on the base?* If
either is yes, re-trigger or rebase first — investigating a stale verdict produces
a plausible root cause for something that is not happening.

**Tags**: `#ci` `#github-actions` `#review-attestation` `#issue-1189`
