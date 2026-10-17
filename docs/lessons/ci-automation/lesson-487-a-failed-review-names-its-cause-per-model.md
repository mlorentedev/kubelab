---
id: lesson-487-a-failed-review-names-its-cause-per-model
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, review-attestation]
---

# A failed review names its cause per model; read it before filing it under a known one

**Context**: PR-Agent is the reviewer whose capacity is ours (`.github/workflows/pr-agent.yml`). `.pr_agent.toml` names a primary model (`openai/mimo-v2.5`, line 38) and one fallback (`openai/deepseek-v4-flash`, line 76), both on NaN. When no review is published, the job's last step, `Fail if no review was published`, fails the run and lists two possible causes.

**Problem**: on #1942 (2026-09-30) two runs failed, and they were filed as #1205's "case 2", an empty body from the primary with no fallback attempted. That diagnosis came from memory, not from the log. The log said something else, one line per model:

```
Generating prediction with openai/mimo-v2.5
Error during LLM inference: litellm.AuthenticationError: ... This API key does not have access to the requested model.
Failed to generate prediction with openai/mimo-v2.5
Generating prediction with openai/deepseek-v4-flash
Error during LLM inference: litellm.Timeout: ... timeout value=120.0, time taken=361.6 seconds   (twice)
Failed to review PR: Failed to generate prediction with any model of ['openai/mimo-v2.5', 'openai/deepseek-v4-flash']
```

The runs were `36677361269` attempt 2 and `36680494106`. Attempt 1 of `36677361269` is a different failure, the cancellation in lesson-486. All four PR-Agent runs read that day, including the two that published reviews (#1945, #1946), opened with the same `AuthenticationError` on the primary. So the primary is not flaky: the key cannot reach it at all. A review lands only when the fallback answers before its timeout. That is neither of the two causes the failing step lists, and #1205 was already closed. The real causes were tracked elsewhere: kubelab#1843 (TOOL-082, NaN stopped serving the configured models) and the dotfiles harness tickets that retire `mimo-v2.5` and stream the NaN calls the edge cuts. Filed under the wrong ticket, the evidence would have gone where nobody fixing the cause would read it.

**Solution**: read the per-model lines before attributing. For each model, `Generating prediction with <model>` is followed by one of two things: `Failed to generate prediction with <model>` with the `Error during LLM inference` line that says why, or nothing at all. That sequence is the diagnosis. Put the measurement on the ticket that owns the cause (here, a comment on #1843), not on the one that matches the symptom.

**Rule**:

- **Attribute a failed review from its log, per model, never from the failing step's summary or from a past incident.** The summary lists the causes someone anticipated. The log names the one that happened.
- **A green-looking or absent review is not a review.** Decide from content, through the `review-attestation` gate, never from the run's colour.
- **Before merging on a PR-Agent review, read the review-state block it embeds.** It must say `"complete":true`, and `last_seen_head_sha` must equal the PR head. A review of an earlier head does not cover later pushes: #1915 merged, and #1916 had to carry a finding PR-Agent posted after the merge.
- **Disclose every unreviewed or substitute-reviewed merge in the squash body.** Proceeding unreviewed is allowed. Proceeding silently is not.

**Tags**: `#pr-agent` `#review` `#review-attestation` `#diagnosis` `#pr-1942` `#issue-1843`
