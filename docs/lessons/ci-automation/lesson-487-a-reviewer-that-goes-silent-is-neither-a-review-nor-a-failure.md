---
id: lesson-487-a-reviewer-that-goes-silent-is-neither-a-review-nor-a-failure
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, review-attestation]
---

# A reviewer that goes silent is neither a review nor a failure

**Context**: PR-Agent is the reviewer whose capacity is ours (`.github/workflows/pr-agent.yml`). Its primary model, `openai/mimo-v2.5` on the NaN cluster, sometimes returns an empty or truncated body on HTTP 200.

**Problem**: no exception is raised on that response, so the fallback chain in `.pr_agent.toml` never fires (#1205, "case 2"). The job's own step, `Fail if no review was published`, then fails the run. The failure names no cause. The log tells this case apart from the rest: it goes silent after `Generating prediction with openai/mimo-v2.5` and never names a second model.

It recurs. Counts of runs that ended this way: 3 on #1942 (2026-09-30, among them 36677361269 and 36680494106), 4 on #1925, 5 on #1890 and 2 on #1885. A related hang is tracked as #1909 (TOOL-087). The consequences were real merges: #1890 and #1925 merged with the `merged-unreviewed` label, and #1942 merged on CodeRabbit's review with the operator's authorisation.

**Solution**: until #1205 and #1909 fix the run itself, the defence sits in how a merge is decided. The `review-attestation` gate reads the content of what was posted, and the reviewers it counts are declared in `harness/review-attestation.json`. A red PR-Agent run is not read as "no findings", and a green one is not read as "reviewed".

**Rule**:

- **A green-looking or absent review is not a review.** Decide from content, through the `review-attestation` gate, never from the run's colour.
- **Before merging on a PR-Agent review, read the review-state block it embeds.** It must say `"complete":true`, and `last_seen_head_sha` must equal the PR head. A review of an earlier head does not cover later pushes: #1915 merged, and #1916 had to carry a finding PR-Agent posted after the merge.
- **Disclose every unreviewed or substitute-reviewed merge in the squash body.** Proceeding unreviewed is allowed. Proceeding silently is not.

**Tags**: `#pr-agent` `#review` `#review-attestation` `#silent-failure` `#pr-1942` `#issue-1205` `#issue-1909`
