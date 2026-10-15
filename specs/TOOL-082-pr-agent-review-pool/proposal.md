---
id: "TOOL-082-pr-agent-review-pool"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-14"
issue: "mlorentedev/kubelab#1843"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, ci, review, pr-agent, inference, budget]
template_version: "1.0"
wip_override: "Reviewer outage: PR-Agent is the only reviewer that clears review-attestation and times out on large diffs, blocking other PRs; owner-prioritised 2026-10-15 (16 active, limit 10, 2026-10-14)"
---

# TOOL-082: PR-Agent review pool

## Why

<!-- from issue #1843: TOOL-082: PR-Agent fails every review since NaN stopped serving both configured models -->

PR-Agent is the only reviewer whose capacity is ours. It is also the reviewer that clears `review-attestation` when CodeRabbit and Codex are out of quota. Today it depends on NaN alone: two models, no probe, and no member from another provider. When NaN retires a model, the chain fails silently (#1964). When a large diff hangs, the job is cancelled at 13 minutes with no review (#1909). When the primary spends its output on reasoning, it publishes nothing (#1966). Each of these leaves the PR red, and other PRs and lanes wait behind it.

dotfiles solved this class with ADR-046 (dotfiles #1923, #2188): a model preflight, a weighted draw that includes Haiku, and a Sonnet risk route for large or `deep-review` PRs. This spec ports that design to kubelab, keeping kubelab's own contracts.

## What

1. **One pool file.** `harness/reviewer-pool.json` takes dotfiles' unified schema (owner, 2026-10-15). Each member declares `vendor` and `secret_id` or `auth` (closes #1561). Members that PR-Agent may use carry a `pr_agent` block with `model`, `weight` and `reasoning_effort`. `pr_agent_risk` declares `min_changed_lines: 1500` and `label: deep-review`.
   - kubelab adopts ADR-046's **amendment B** for its adversarial review as well: an Anthropic model never signs alone. Haiku signs only as `fallback` and Sonnet only as `second`.
   - This is recorded in a kubelab ADR that extends dotfiles' ADR-046.
2. **Preflight.** `scripts/pr-agent-model-preflight.sh` probes each model of the declared NaN chain once, before the review.
   - It names every model that does not answer, with its status class, in a warning and in the job summary.
   - It never admits a model outside the chain.
   - The chain declared in the workflow is held equal to `.pr_agent.toml` by a test (#1964).
3. **Draw.** `scripts/pr-agent-route.sh` picks the first attempt from the members that answered, by declared weight.
   - Initial weights are dotfiles': mimo 27, glm 19, deepseek 19, Haiku 35.
   - A PR with at least 1,500 changed lines, or the `deep-review` label, reviews first on Sonnet. If Sonnet does not answer, the PR goes to the draw with a note.
   - The Anthropic models CI may spend on are an allowlist inside the script, each with a price row and a worst-review ceiling enforced by a test.
   - `vars.PR_AGENT_PROVIDER` overrides the draw (`draw`, `nan`, `anthropic`, `nan-only`). `nan-only` stops all Anthropic spend without a PR.
   - Inputs are `PR_CHANGED_LINES` and `PR_LABELS` from the environment, not GitHub event fields, so TOOL-117's forge reviewer can reuse the script.
4. **Two attempts, two providers.** The second provider runs only on a *measured* absence of a published review: `scripts/pr-agent-publish-guard.sh --probe`. The Anthropic attempt has these settings:
   - effort `medium`, with adaptive thinking;
   - an output cap of 40,000 tokens;
   - no temperature;
   - a prompt cap of 200,000 tokens;
   - `PR_AGENT_ANTHROPIC_API_KEY` as its only credential.

   The NaN attempt keeps streaming, and both attempts share the action pin and every review setting.
5. **Every review names its model** (`CONFIG__OUTPUT_RUN_DETAILS: "true"`). A reader, and this spec's verification, can see which member reviewed without opening the run.
6. **Contracts preserved.** These stay unchanged:
   - the workflow name `pr-agent`, read by `review-attestation.yml`'s `workflow_run`;
   - the `pr-number` artifact, uploaded first;
   - the review marker, read from `harness/review-attestation.json` on the default branch;
   - the reviewable, stale-label and declare-unreviewed steps;
   - the job and workflow concurrency groups, with `queue: max`;
   - the Dependabot, release and deploy skips.

   The final guard reports the outcome of the last attempt that ran. The job and step timeouts are re-derived from the attempts' bounds and pinned by tests.

## Out of scope

- A reusable workflow shared by dotfiles and kubelab, the forge (Gitea) reviewer reading this pool, and the other PR-Agent repositories: TOOL-117 (#2295).
- dotfiles' incremental push gate (`/review -i`, dotfiles TOOL-023). kubelab keeps full reviews on push.
- Re-weighting. It waits for dotfiles' AI-052 and AI-053 measurements (dotfiles#2215, #2216). kubelab starts with dotfiles' weights.

## Risks / open questions

- **Shared budget.** kubelab spends from the one Console limit of $60-65 a month that ADR-046 sized for every repository. The owner approved this on 2026-10-15, with the basis on #1843. dotfiles measured about $3-8 per 30 days, and kubelab projects about $4-10. The spend limit is the backstop. `nan-only` is the switch.
- **Same-vendor review.** About a third of reviews are by Haiku, a Claude model, on changes Claude wrote. This is accepted for PR-Agent, as in dotfiles. The adversarial review keeps a first signature from another vendor (amendment B).
- **The secret arrives after the code.** dotfiles#2508 adds the consumer, and the sync waits until the wiring PR is open, per the registry's rule. Without the secret, the draw degrades to NaN only and says so.
- **A slash command runs the default branch's workflow** (lesson-553). The wiring PR reviews itself on `pull_request`. A `/review` on it would use master's NaN-only copy until merge.

## Acceptance criteria

- [ ] **AC1** `harness/reviewer-pool.json` has the unified schema. A test fails if an Anthropic member could sign first, if a member declares neither `secret_id` nor `auth`, or if a PR-Agent model is absent from the pool. A kubelab ADR records amendment B.
- [ ] **AC2** A retired or unanswering NaN model produces a warning that names the model and its status class, and the review still runs on a member that answered. The workflow's NaN chain equals `.pr_agent.toml`'s, by test.
- [ ] **AC3** The draw is tested:
  - it follows the declared weights;
  - a member that did not answer gives its weight to the rest;
  - the risk route triggers at 1,500 lines but not at 1,499, and on the exact label only;
  - Sonnet is never drawn;
  - an Anthropic model outside the allowlist fails the draw;
  - an unknown `PR_AGENT_PROVIDER` fails;
  - each allowed model has a price row with its worst review under its ceiling.
- [ ] **AC4** In `pr-agent.yml`:
  - the second attempt runs only when the publish probe says nothing was published;
  - both Anthropic attempt copies are identical;
  - every attempt shares the review settings;
  - the timeouts fit inside the job.

  Each of these is asserted by `tests/test_pr_agent_workflow.py`, and the existing attestation tests stay green.
- [ ] **AC5, live, normal PR:** a kubelab PR under 1,500 lines gets a published `PR Reviewer Guide` that names its model. The run's job summary names the member drawn.
- [ ] **AC6, live, risk route:** a review on Sonnet is published inside the job, with the run details naming Sonnet. The PR is either a large PR that previously timed out (for example #1885, at 1,506 changed lines, re-reviewed with `/review` after merge) or a PR carrying `deep-review`.

## References

- Bitácora: #1843. It also closes #1964 (TOOL-095), #1909 (TOOL-087), #1966 (TOOL-096) and #1561.
- Debt left outside: TOOL-117 (#2295).
- dotfiles: ADR-046, `docs/runbooks/guide-pr-agent-reviewer.md`, `specs/archive/AI-045-nan-catalog-alignment/`, and #2508 (the secret consumer).
- Budget basis: #1843 comment 6182661458, dotfiles#2215 comment 6182665477.
