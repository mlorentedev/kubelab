---
id: lesson-411-a-review-guard-s-two-known-causes-are-not-exhaustive
type: lesson
status: active
created: "2026-09-01"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, pr-agent, review-attestation, sops]
---

# A review guard's two documented failure causes were not exhaustive — a third, structural one hid behind an identical error

**Context**: `pr-agent.yml`'s `Fail if no review was published` step (CI-GATE-011, #1140) exists to catch PR-Agent reporting job-success while publishing nothing. Its own error message names two causes: saturation (a 429 exhausts the fallback chain) and an empty/truncated body on a 200 (the model spends its output budget on reasoning). Both #1514 and #1523 tripped this guard the same night.

**Problem**: Neither documented cause was the real one. Both PRs touch exactly one file — `infra/config/secrets/prod.enc.yaml` — which `.pr_agent.toml`'s own `[ignore] glob` deliberately excludes (SOPS ciphertext is never sent to the model). The run log showed the actual sequence: `get_pr_diff` computes a real diff for token accounting ("Tokens: 16162... returning full diff"), but `_prepare_prediction` separately re-derives the reviewable set after the ignore filter and finds it empty — `"Filtered out [ignore] files for pull request:", "extra": {"files": ["infra/config/secrets/prod.enc.yaml"], "filtered_files": []}` followed by `"Empty diff for PR"`. No exception, no comment, nothing published — indistinguishable from the guard's own two causes purely by *symptom* (a green PR-Agent step, no review comment, guard fires), even though the mechanism is a third, structural one: the diff was legitimately, deliberately empty by design, not starved or truncated.

**Solution**: Added a step ahead of PR-Agent that fetches the PR's changed files and checks them against `.pr_agent.toml`'s ignore globs — read from the repository's default branch, never the PR head, so a PR author cannot add `"**"` to their own branch's config and auto-skip review with a green gate. When every changed file is excluded, PR-Agent and the guard are both skipped and the PR is declared unreviewed via the same registry-driven escape (`merged-unreviewed` label + `## Unreviewed merge rationale`) already used for Dependabot's structurally-missing-credential case — but with rationale text that does *not* suggest `/review` as a fix, since a retry hits the identical empty diff. A companion step clears a stale escape label if the same branch later gains a reviewable file, so the declaration doesn't outlive its own cause.

**Rule**: A guard's documented failure causes are a snapshot of what has been *seen*, not a proof of what is *possible*. Two failure modes that look identical from the outside (same error, same missing artifact) can have unrelated root causes — cross-check the actual mechanism (here: which files were filtered, and by what) before assuming a new instance matches a known cause. And: any ignore/exclude list that feeds a review or security gate needs an explicit "what if everything is excluded" path — a filter with no members left is not the same failure as the filter failing, and treating it as one produces confident, wrong error messages under `set -euo pipefail`.

**Tags**: `#ci-automation` `#pr-agent` `#review-attestation` `#sops` `#issue-1527`
