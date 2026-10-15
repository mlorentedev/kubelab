---
id: "adr-070"
type: adr
status: accepted
owner: manu
date: "2026-10-15"
issue: "kubelab#1843"
tags: [architecture, decision, review, pr-agent, ci, inference, budget]
depends_on: []
created: "2026-10-15"
---

# ADR-070: The Reviewer Pool Adopts dotfiles' ADR-046 (an Anthropic Reviewer Never Signs Alone)

## Status

Accepted, 2026-10-15. The owner chose the unified pool and approved the budget on #1843 (TOOL-082). Spec:
`specs/TOOL-082-pr-agent-review-pool/`. It extends mlorentedev/dotfiles ADR-046
(`docs/adr/adr-046-anthropic-reviewers-never-sign-alone.md` there) and does not restate it.

## Context

kubelab reviews through two flows. Both are bounded by the same NaN models:

- **PR-Agent in CI.** It is the only reviewer whose capacity is ours, and it is the one that clears
  `review-attestation` when CodeRabbit and Codex are out of quota (TOOL-021). It depended on NaN alone:
  - NaN retired a model, and every review failed with nothing naming the cause (#1843, #1964);
  - a large diff hung until the job was cancelled at 13 minutes (#1909);
  - the primary spent its output on reasoning and published nothing (#1966).

  Each of these left a PR red, and other lanes waited behind it.
- **The adversarial review.** `dotf spec review` and `dotf spec archive` read `harness/reviewer-pool.json`. That file held
  a standing rule that no Anthropic model ever reviews here, because Claude implements nearly every change and
  dotfiles' BUG-074 was reviewed twice by the model family that wrote it. None of its members declared a credential,
  so the launcher injected the whole secret store (#1561).

dotfiles solved the first problem and relaxed the second rule in ADR-046 (mlorentedev/dotfiles#1923, #2188). That
design has run since 2026-10-09. Its first measurement, 2026-10-09 to 10-15 (mlorentedev/dotfiles#2215), covered
234 drawn reviews:

- the shares matched the declared weights;
- one review took the risk route;
- the Anthropic spend was about $3-8 per 30 days.

## Decision

1. **One pool file, dotfiles' shape.** `harness/reviewer-pool.json` serves both flows.
   - Every member declares `vendor` and exactly one of `secret_id` or `auth`.
   - The members that PR-Agent may use carry a `pr_agent` block: model, weight and reasoning effort.
   - `pr_agent_risk` holds the risk predicate.
   - The file is a port of dotfiles' copy. The two copies are kept in step by hand until TOOL-117 (#2295) gives both
     repositories one source.
2. **Amendment B applies here too.** An Anthropic model never signs an adversarial review alone. Haiku signs only as
   `fallback`, with a classified reason, and Sonnet only as `second`. A first signature always comes from another
   vendor. This replaces the old "never Anthropic" rule. `dotf spec archive` already enforces it at pool load.
3. **PR-Agent draws by declared weight**, with dotfiles' starting weights: mimo 27, glm 19, deepseek 19, Haiku 35.
   - A NaN model that fails its preflight gives up its weight for that run.
   - A PR with 1,500 or more changed lines, or the `deep-review` label, reviews first on Sonnet.
   - The Anthropic models CI may spend on are an allowlist in `scripts/pr-agent-route.sh`, priced and capped by a test.
4. **One budget for every repository.** kubelab spends from the Console limit ADR-046 set at $60-65 a month. That limit
   was sized on the volume of all 13 PR-Agent repositories, so kubelab is not an addition to it (owner, 2026-10-15).
   - Projected kubelab spend is about $4-10 a month.
   - `vars.PR_AGENT_PROVIDER=nan-only` stops all Anthropic spend without a PR.
   - The spend limit is the backstop, not the budget.

## Consequences

- PR-Agent no longer fails with its provider. A dead or hung NaN model is named and skipped. A review that published
  nothing is retried once on the other provider, and the large diffs that timed out reach a model that answers them.
- About a third of PR-Agent reviews are written by a Claude model on changes Claude wrote. For PR-Agent this is
  accepted, as in dotfiles. Every adversarial review still carries a first signature from another vendor.
- A high-risk spec's second signature depends on the Anthropic review key, which is a deliberate single point of
  failure, as in ADR-046.
- The adversarial pool here gains dotfiles' members: glm, qwen, and gemini-3.8-flash-high in place of the retired
  gemini-3.1-pro-high. It also inherits their admission records.
- Two copies of one file now exist, and the drift between them is TOOL-117's.

## Alternatives considered

- **A separate PR-Agent pool file, with the adversarial rule untouched.** It would have kept #1843 smaller, but it
  would have left two files here disagreeing about who may review, which is the defect
  `test_every_model_pr_agent_reviews_with_is_admitted_in_the_reviewer_pool` exists to prevent. It would also have
  diverged from dotfiles' shape, which TOOL-117 has to converge. The owner rejected it on 2026-10-15.
- **Haiku only, no draw.** The measured cost is about the same, $3-15 a month. Rejected because every CI review would
  be same-vendor on the one reviewer that clears the gate.
- **Fix the NaN chain only (#1843's original scope).** Rejected because it has failed three different ways in three
  weeks (#1843, #1909, #1966). A second provider is the fix for the class, not for one instance.
