---
id: lesson-446-a-dependabot-pull-request-reads-an-empty-secret-store-so-a-reviewer-that-needs-one-must-say-it-cannot-run
type: lesson
status: active
created: "2026-08-24"
owner: manu
category: ci-automation
tags: [kubelab, ci-automation, github-actions, dependabot, pr-agent, review-attestation, secrets, pr-1374]
---

# A Dependabot pull request reads an empty secret store, so a reviewer that needs a credential must say it cannot run — not fail

**Context**: Five Dependabot PRs (#1358–#1362) went red on the same two checks the night the review-attestation gate (TOOL-021, #1140) became required. The run log named the cause without being asked:

```
Secret source: Dependabot        <- Dependabot-triggered run
  OPENAI__KEY:                   <- empty
```
```
Secret source: Actions           <- human PR #1357, same night
  OPENAI__KEY: ***
```

**Problem**: A `pull_request` event raised by Dependabot reads the **Dependabot secret store**, and `gh api repos/.../dependabot/secrets` returns nothing for this repository, so every `secrets.*` resolves to an empty string. `review` published nothing because `NAN_API_KEY` was empty, `review-attestation` then correctly reported no review, and `Build & Push` on #1358 failed with `Username and password required` because `DOCKERHUB_*` was empty. The token was not the obstacle — the same log shows `PullRequests: write`, so `permissions:` does elevate `GITHUB_TOKEN` for Dependabot events. Dependabot's isolation is long-standing GitHub behaviour; what changed was ours: the attestation gate turned "no review happened" into a required red check, and before it bot PRs merged because nothing asked. `pr-agent.yml` had already reasoned about this exact shape for fork PRs and filed it as *"currently hypothetical"*. The defect was the un-revisited premise, not the reasoning.

**Solution**: Rejected the obvious fix — mirroring secrets into the Dependabot store puts a model credential and a registry **push** credential within reach of a branch no human wrote, to LLM-review version bumps. Instead: (1) the reviewer is **skipped, not left to fail**, on the `pull_request` branch of its condition only — a human `/review` runs in the repository context, which carries the credential, and a test pins that asymmetry; (2) `dependabot-declare-unreviewed.yml` applies the gate's own escape — the label and the body section, both read from `harness/review-attestation.json` so workflow and judge cannot disagree — and its `if` is asserted by a test to never widen beyond the bot; (3) the publish job skips the bot, since `CI + Build` already builds the image on every PR and master publishes after merge. Seven guards, `make test-fast` 1387 passed.

**Rule**: A reviewer that cannot run is not a reviewer that found nothing, and a job red on every dependency bump teaches people that red is normal. When a bot's event context cannot carry a credential, skip the step that needs it *and* declare the consequence in the durable record ("merged unreviewed") rather than hand the credential to the bot. Automating a disclosure whose reason is identical every time is still a disclosure; automating the label's *meaning* would not be. Any "currently hypothetical" comment about an execution context is a premise with an expiry date — revisit it when the gate that depends on it becomes required.

**Tags**: `#github-actions` `#dependabot` `#pr-agent` `#review-attestation` `#secrets` `#unreviewed-merge` `#pr-1374`
