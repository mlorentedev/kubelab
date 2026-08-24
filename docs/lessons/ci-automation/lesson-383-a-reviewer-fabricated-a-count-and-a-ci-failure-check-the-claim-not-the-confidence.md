---
id: lesson-383-a-reviewer-fabricated-a-count-and-a-ci-failure-check-the-claim-not-the-confidence
type: lesson
status: active
created: "2026-08-23"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-review, pr-agent, coderabbit, codex, quota, tool-021]
---

# A reviewer fabricated a count and a CI failure that never happened — check the claim, never the confidence

**Context**: An evening of PRs closing out the credential rotation (#1348, #1349, #1353, #1354, #1357). Codex and CodeRabbit were both over quota for the whole window; `pr-agent` was the reviewer that actually ran.

**Problem**: Two failure modes appeared on the same PRs, and they call for opposite responses.

1. **Quota notices are not reviews.** Codex and CodeRabbit posted comments all evening that talked about the *review* rather than about the code — "review limit reached", "we couldn't start this review". A comment arrived, the PR looked attended, and nothing had been read. Tell them apart by content, never by author or by the presence of a comment: a review names files, lines or claims; a notice talks about itself. This is the shape [lesson-347](lesson-347-a-pr-reviewer-s-check-status-cannot-tell-a-re.md) and [lesson-353](lesson-353-a-reviewer-reports-its-own-status-and-a-skip.md) already describe from the check-status side.
2. **A reviewer that *did* run asserted things that were not true.** `pr-agent` found a genuine shell-injection gap in `expire_headscale_preauthkey` — applied. On another PR the same reviewer stated a specific count (`362`) and reported a CI failure, both delivered in the same assured register as the real finding. Neither existed. The specificity of a number is not evidence for it; a fabricated `362` reads exactly like a counted one.

Operationally there is also a discovery problem: `pr-agent` posts its real review as a **"PR Reviewer Guide" issue-comment**, which lands underneath CodeRabbit's notices in the thread. The one review worth reading is the one hardest to see.

**Solution**: Every reviewer claim gets checked against the repo before it is applied or dismissed — the injection finding by reading the function, the `362` and the CI failure by running the count and opening the check. Both categories were dispositioned in the PR's `## Review triage` comment, including the notices, since "a notice arrived and no review ran" is itself a disposition and leaving it unwritten is indistinguishable from nobody having looked.

**Rule**: Treat reviewer output as a *hypothesis set*, never as findings. Verify each claim against the tree, and weight it by the evidence you can reproduce rather than by how confidently it was stated — an accurate finding and a hallucinated one arrive in the same tone, from the same reviewer, in the same comment. Separately: before concluding a PR was reviewed, confirm a review exists by content. `review-attestation` (TOOL-021, #1140) asks precisely this question because a spent quota renders as `success`.

**Tags**: `#pr-review` `#pr-agent` `#coderabbit` `#codex` `#quota` `#hallucination` `#tool-021`
