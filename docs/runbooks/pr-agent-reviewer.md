# PR-Agent reviewer: the review pool

> TOOL-082 (#1843), ADR-070. PR-Agent reviews every PR in `.github/workflows/pr-agent.yml` and is the
> reviewer that clears `review-attestation` when the vendor reviewers are out of quota (TOOL-021). This
> runbook covers operating it. dotfiles `docs/runbooks/guide-pr-agent-reviewer.md` has the measurements
> behind the design.

## What one run does

1. **Preflight** (`scripts/pr-agent-model-preflight.sh`). It probes each model of the declared NaN
   chain (mimo, deepseek, glm) with a small request. A model that refuses, hangs or is over its limit is
   dropped for this run, with a warning that names it.
2. **Draw** (`scripts/pr-agent-route.sh`). It probes Haiku, then draws the first reviewer by the
   `pr_agent.weight` values in `harness/reviewer-pool.json`: mimo 27, glm 19, deepseek 19, Haiku 35.
   A member that did not answer gives up its weight to the others. A PR with 1,500 or more changed lines,
   or the `deep-review` label, reviews first on Sonnet when Sonnet answers.
3. **First attempt.** It runs on the drawn provider: 8 minutes on Anthropic, 19 on NaN.
4. **Probe** (`scripts/pr-agent-publish-guard.sh --probe`). Only a measured "nothing was published" runs
   the **second attempt**, on the other provider. An API failure reads as "unknown" and never runs it.
5. **Final guard** (`scripts/pr-agent-publish-guard.sh`). The job goes red unless a review carrying the
   registry's marker was published by this run. Its error names the last attempt and why.

The job summary shows the preflight table, the member drawn and any member that was out of the draw.
Each published review ends with run details naming the model that wrote it.

## Switches

`vars.PR_AGENT_PROVIDER` overrides the draw without a PR:

| Value | Effect |
|---|---|
| unset, or `draw` | Weighted draw, with the risk route first. |
| `nan` | NaN first, Anthropic second; no risk route. |
| `anthropic` | Anthropic first, NaN second. |
| `nan-only` | No Anthropic model is even probed. **This stops all spending on the Anthropic key.** |

```bash
gh variable set PR_AGENT_PROVIDER --body nan-only --repo mlorentedev/kubelab   # stop Anthropic spend
gh variable delete PR_AGENT_PROVIDER --repo mlorentedev/kubelab                # back to the draw
```

An unknown value fails the draw on purpose: it may be a misspelt `nan-only`.

To ask for the deepest review on one PR, add the `deep-review` label before the review runs, or add it
and comment `/review`.

## Spend

The Anthropic key spends from the one Console limit shared by every repository (ADR-070 §4). The
projection for kubelab is about $4-10 a month. The limit is a backstop: once it is hit, the probe
answers an error, Anthropic leaves the draw, and NaN reviews alone. Watch the month's spend in the
Claude Console. Use `nan-only` to stop spending before the limit is reached.

## When the guard fails

| The guard says | Cause | Do |
|---|---|---|
| `PR_AGENT_ANTHROPIC_API_KEY is not set` (a note) | The secret is not synced to this repository | Add `ci:mlorentedev/kubelab` to its consumers in dotfiles `secrets/registry.yaml`, then `dotf secrets sync ci --repo mlorentedev/kubelab PR_AGENT_ANTHROPIC_API_KEY` |
| `... answered HTTP 401` on an Anthropic model | The key is refused | `dotf secrets rotate PR_AGENT_ANTHROPIC_API_KEY`, then sync |
| `... answered HTTP 401` on a NaN model | NaN retired it, or the key lost access | Replace it in the chain: in the workflow's preflight step, in `.pr_agent.toml` and in the pool. A test holds the three equal. |
| `the draw itself failed` | `PR_AGENT_PROVIDER` is misspelt, or the preflight failed on its setup (exit 2) | Read the draw step's log; it names which |
| `published no review` on NaN | Saturation, an empty answer (#1205, #1966) or a diff too large for the step (#1909) | Comment `/review` to retry; for a large diff, add `deep-review` first |
| `published no review` on Anthropic | No cause is measured yet | Read the attempt's log for an answer cut at the 40,000-token output cap |

## What the job trusts

The scripts that pick the model and judge the result come from the PR's merge ref, not from `master`.
The draw step holds `PR_AGENT_ANTHROPIC_API_KEY`, and the preflight holds `NAN_API_KEY`. A PR can
therefore change the code that runs next to both keys. That is the trust a `pull_request` run already
gives the workflow file, which also comes from the head. The job admits no fork (`head.repo.fork ==
false`) and skips Dependabot, so only people with push access reach it. Accepted in TOOL-082's
review. Revisit it if the job is ever opened to forks or moved to `pull_request_target`.

The credential step checks only `NAN_API_KEY`. A missing Anthropic key is a note, not a failure: NaN
still reviews.

## Changing the pool

- **Weights and members** live in `harness/reviewer-pool.json`, which is a port of dotfiles' copy. Change
  both copies until TOOL-117 (#2295) gives them one source.
- **The NaN chain** is declared three times: the workflow's preflight step (`DECLARED_MODEL`,
  `DECLARED_FALLBACK_MODELS`), `.pr_agent.toml`, and the pool. `tests/test_pr_agent_workflow.py` fails when
  they disagree. PR-Agent reads the toml from the default branch, so the PR making the change reviews
  with the workflow's copy.
- **The Anthropic models CI may pay for** are `ALLOWED_ANTHROPIC` in `scripts/pr-agent-route.sh`. A pool
  naming any other model fails the draw. Changing the allowlist is a cost decision, made in a reviewed PR.
- **Timeouts.** `tests/test_pr_agent_workflow.py` holds the job's 40 minutes against its worst
  two-attempt path. Raise a step's limit and the job's together.
