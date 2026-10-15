---
tags: [spec, tasks, templates]
created: "2026-10-14"
---

# Tasks - TOOL-082-pr-agent-review-pool

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Worktree `../kubelab-pr-agent-pool-wt`, branch `feat/pr-agent-review-pool` from `origin/master` ✓ 2026-10-15
- [x] Gates: budget approved; secret consumer in dotfiles#2508, which is synced once PR 3 is open ✓ 2026-10-15
- [x] Pool shape decided: unified, as in dotfiles (owner, 2026-10-15) ✓ 2026-10-15

Three PRs, each one atomic and each under the 300-line cap excluding tests. PR 1 and PR 2 are inert. PR 3 switches the reviewer and reviews itself.

## Implementation

### PR 1: the unified pool and the ADR (closes #1561)

- [ ] [AC1] Write failing tests in `tests/test_reviewer_pool.py`:
  - every entry has a `vendor` and exactly one of `secret_id` or `auth`;
  - an Anthropic entry declares `signs` as `second` or `fallback`, never first;
  - `pr_agent.weight` is a positive integer and the weights sum to more than 0;
  - exactly one member has `route: risk`, and it has no weight;
  - `pr_agent_risk` is `{min_changed_lines: 1500, label: "deep-review"}`.

  Run `make test PYTEST_ARGS="tests/test_reviewer_pool.py"`. Expected: FAIL (no `vendor`, no `pr_agent`).
- [ ] [AC1] Port dotfiles' `harness/reviewer-pool.json` entries and `pr_agent_risk`. Keep kubelab's `$comment` history and rewrite the standing rule as amendment B. Expected: PASS.
- [ ] [AC1] Make `test_every_model_pr_agent_reviews_with_is_admitted_in_the_reviewer_pool` match on `pr_agent.model`, not on the id suffix. Run `tests/test_pr_agent_workflow.py` and expect PASS.
- [ ] [AC1] Check that `dotf spec review` still loads the pool: run `dotf spec review --help` against a spec with no side effects, or the CLI's pool validation. Record the output in `verification.md`.
- [ ] [AC1] Write `docs/adr/adr-070-*.md`: kubelab adopts dotfiles ADR-046, covering amendment B, the weighted draw, the risk route and the shared budget.

### PR 2: the three scripts, inert (refs #1964, #1909)

- [ ] [P] [AC2] Write failing tests in `tests/test_pr_agent_preflight.py`, which run the script against a local HTTP stub (`http.server` in a thread):
  - the first model that answers is chosen;
  - a 401 is named as "the chain is wrong", a 429 as quota, a hang or 5xx as "NaN is not serving";
  - exit 1 when none answers, exit 2 on a usage error;
  - a model outside the chain is never admitted.
- [ ] [AC2] Port `scripts/pr-agent-model-preflight.sh`. Expected: PASS.
- [ ] [P] [AC3] Write failing tests in `tests/test_pr_agent_route.py`:
  - `PR_AGENT_DRAW` boundaries follow the cumulative weights;
  - a dead member's weight is shared out;
  - the risk route triggers at 1500 but not at 1499, and on the exact label only;
  - when Sonnet does not answer, the PR falls to the draw with a note;
  - Sonnet is never drawn;
  - the allowlist refuses another model before any probe;
  - an unknown `PR_AGENT_PROVIDER` gives exit 1, and `nan-only` probes no Anthropic model;
  - the key is never on argv;
  - each allowed model has a price row with its worst review under its ceiling.
- [ ] [AC3] Port `scripts/pr-agent-route.sh`, with `POOL_FILE` defaulting to `harness/reviewer-pool.json`. Expected: PASS.
- [ ] [P] [AC4] Write failing tests in `tests/test_pr_agent_publish_guard.py`:
  - `--probe` answers `published=true|false` from a stubbed comment list;
  - only `github-actions[bot]` comments count;
  - a comment must be updated after the start stamp;
  - the marker is read from the default branch's registry;
  - the head-registry fallback for a bootstrap PR is kept.
- [ ] [AC4] Port `scripts/pr-agent-publish-guard.sh`, carrying over kubelab's inline guard logic and error text, which keeps both of its causes. Expected: PASS.

### PR 3: the wiring, which reviews itself (closes #1843, #1964, #1909, #1966)

- [ ] [AC4] Write failing tests in `tests/test_pr_agent_workflow.py`:
  - the scripts are checked out sparsely at the PR head; the data read stays on the default branch;
  - the preflight chain equals the toml chain;
  - the route step's inputs come from the API, not the event;
  - both Anthropic attempt copies are identical;
  - the review settings are equal across all attempts;
  - every attempt sets `CONFIG__OUTPUT_RUN_DETAILS`;
  - the second attempt is gated on the probe output;
  - the job timeout is at least the steps' bounds plus their overhead;
  - the credential step accepts NaN-only.
- [ ] [AC4] Wire `.github/workflows/pr-agent.yml`:
  - sparse checkout, then the preflight, the route, the Anthropic attempt first, the probe, the NaN attempt, the probe, and the Anthropic attempt second;
  - the final guard becomes `pr-agent-publish-guard.sh`;
  - the timeouts are re-derived.

  Expected: the whole suite PASSES (`make test`).
- [ ] [AC4] Update `.pr_agent.toml` so its chain matches the preflight's (mimo, deepseek, glm), and admit glm in the pool.
- [ ] Document the reviewer in a runbook, `docs/runbooks/pr-agent-reviewer.md`: the provider switch, the spend, reading the job summary, and the gates.
- [ ] Open PR 3 as a draft. Merge dotfiles#2508 under its merge grant. Run `dotf secrets sync ci --repo mlorentedev/kubelab PR_AGENT_ANTHROPIC_API_KEY`, then `gh pr ready`.
- [ ] [AC5] Normal review: PR 3's own `pull_request` run publishes a Reviewer Guide. Record the run id, the member drawn, and the run details.
- [ ] [AC6] Risk route: add `deep-review` to PR 3, push, and see Sonnet published. After merge, comment `/review` on #1885 (1,506 lines, which timed out on 2026-09-29) and see a published review within the job. Record both.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] `make test` passes; `make lint` passes
- [ ] No unrelated changes in the diff
- [ ] `verification.md` filled in, with AC5/AC6 evidence (run ids)
- [ ] Adversarial review (`dotf spec review`) before archive
