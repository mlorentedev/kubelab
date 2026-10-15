---
tags: [spec, verification, templates]
created: "2026-10-14"
---

# Verification - TOOL-082-pr-agent-review-pool

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] **AC1**: `tests/test_reviewer_pool.py` (vendor, credential path, amendment B, draw and route shape, risk predicate) and `test_every_model_pr_agent_reviews_with_is_admitted_in_the_reviewer_pool`, now matched on `pr_agent.model`. The CLI enforces amendment B on load, measured 2026-10-15 with dotf at the commit that added the pool:
  - `dotf spec review TOOL-082-pr-agent-review-pool --dry-run --reviewer anthropic-review/claude-haiku-5-5` is refused with `it is a fallback, which signs first only when the first signers failed: pass --fallback-reason`;
  - the same with `--fallback-reason quota` builds the launch command;
  - `--reviewer nan/glm5.3-flash` builds the launch command.
  - `--reviewer agy/gemini-3.8-flash-high` builds `agy --model gemini-3.8-flash-high ...` with no `--provider` flag and no `dotf secrets run --only` wrapper. That is the `auth: login` path, so the arm launches without the key it used to name (#2298 review).

  `test_another_vendor_can_sign_first` holds the other half of amendment B: a first signer from outside Anthropic exists.

  ADR: `docs/adr/adr-070-review-pool-adopts-dotfiles-adr-046.md`.
- [x] **AC2**: `tests/test_pr_agent_preflight.py`, 13 tests: 10 against a stubbed `curl`, 3 against the real `curl` and a local HTTP server (an answer, a hang to the timeout, a 200 status line whose body never arrives). Mutation `2??)` to `2xx)` in the script: 10 failed.
- [x] **AC3**: `tests/test_pr_agent_route.py`, 43 tests (1 added after the independent review: the default effort). They cover the cumulative draw at every point, the shipped pool's weights, the risk route at 1,500 and not 1,499, the exact label, the allowlist, the `PR_AGENT_PROVIDER` values and the key on stdin only. Mutation `-ge` to `-gt` on the risk line: 2 failed.
- [x] **AC4**: the guard is in `tests/test_pr_agent_publish_guard.py`, 26 tests (2 added after the independent review: a pasted heading from a non-bot author, and the head fallback's generic marker). Mutation "an API failure answers `published=false`": the 3 "unknown, never false" tests failed. Workflow half: `tests/test_pr_agent_workflow.py`, 74 tests, 14 of them new or rewritten for the pool. They check the attempt order the guard reads, one action pin, the two Anthropic copies identical, equal review settings, each attempt holding only its provider's key, the probes gating the second attempt, the allowlist against the pool and the workflow, the price ceiling per allowed model, the sparse checkout, size and labels read from the API, and the job outlasting its worst two-attempt path. Three mutations went red under `make mutate`:
  - NaN step `timeout-minutes: 19` to `13`;
  - the second attempt gated on `!= 'true'` instead of `== 'false'`;
  - Opus added to `ALLOWED_ANTHROPIC`.

  `actionlint` reports only the 5 SC2016 infos that master already has.
- [x] **AC5** (normal PR, drawn): live on #2302 once it was merged with master: 720 changed lines, under the threshold, no label. Run 38686296555 on 9d8e35a7: the draw logged `PR-Agent reviews first on anthropic/claude-haiku-5-5 (draw, override: draw); second attempt: nan`, and the guard logged `review published (markers: ["## PR Reviewer Guide"]) on anthropic/claude-haiku-5-5`. The Reviewer Guide's run details name the model: 67,511 tokens in, 1,948 out, 14.3 s. A NaN member drawn first is the path every PR before this one has taken.
- [x] **AC6** (risk route on Sonnet): live on #2302 at 2,926 changed lines, above the threshold. That diff carries all of #2301, which had timed out on NaN twice, in runs 38677984410 and 38679691418 (`The action 'PR-Agent' has timed out after 13 minutes`). That makes #2302 "a large PR that previously timed out". Run 38685369694 on 55f12ad3: the draw logged `PR-Agent reviews first on anthropic/claude-sonnet-5-5 (risk, override: draw); second attempt: nan`, and the guard logged `review published (markers: ["## PR Reviewer Guide"]) on anthropic/claude-sonnet-5-5`. Run details: 116,858 tokens in, 1,641 out, 19.1 s, one call, full diff. The first Sonnet run (38683281099, on 4a616727) was refused before it reached the API, because `.pr_agent.toml`'s `custom_llm_provider = "openai"` applies to every model (lesson-575). 55f12ad3 sets `LITELLM__CUSTOM_LLM_PROVIDER: anthropic` on both Anthropic attempts, and the streaming test now requires it (red without it). The `deep-review` **label** route is covered by unit tests only (`test_the_label_routes_a_small_pr_to_the_risk_member_and_only_the_exact_label`). The criterion reads "either ... or", and the size route is the one exercised live. The `/review` on #1885 after merge is a further check, recorded on #1843.

## Test status

- Test suite: `poetry run pytest` at 8c2a1c2e gave 5180 passed, 18 skipped, 164 deselected and 2 xfailed in 517.92 s. That run was the pooled adversarial review's, in this session. The five PR-Agent suites alone give 186 passed. `actionlint`: only the 5 SC2016 infos master already has. `shellcheck -S style` on the three scripts: clean.
- Manual smoke test: three live PR-Agent runs on #2302, recorded under AC5 and AC6, plus the refused first Sonnet run that found lesson-575.
- No regressions in existing test suite: yes. No test was deleted. The rewritten guards got stronger: each mutation listed above went red.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- The pool is dotfiles' file transformed, not rewritten:
  - dotfiles issue numbers are qualified as `mlorentedev/dotfiles#N`, and dotfiles-only paths are prefixed `dotfiles`;
  - a header records the source commit;
  - kubelab's own deepseek measurement (#1205) is kept.

  Rewriting the admission records by hand would have produced a third version of the same facts.
- Timeouts: the NaN step is 19 minutes, so that `ai_timeout=360` (measured here, #1962) fits the three-model chain: 3 x 360 s + 60 s. The job is 40 minutes, against a worst two-attempt path of about 37 minutes. dotfiles' 12/32 do not transfer, because dotfiles runs PR-Agent's default 120 s timeout. Cutting the chain to two models would have kept glm out of the draw that ADR-070 weighs.
- The WIP gate refused a new spec (16 active against a limit of 10). The owner overrode it on 2026-10-15; the reason is recorded as `wip_override` in `proposal.md`.

- Pooled review round 1 (`nan/qwen3.8-flash`, FAIL on the scaffold `features.json`). Dispositions:
  - Applied: `features.json` written, one entry per criterion. AC5 and AC6 evidence swapped into the criteria whose text they satisfy. Test status and promotion lines filled.
  - Declined: making `CONFIG__MODEL_WEAK` symmetric. kubelab's toml declares no `model_weak`, so the NaN attempt's weak model is its model, as on the Anthropic attempts. The override stays so that a `model_weak` added to the toml later cannot send a Claude attempt's weak calls to NaN.
  - Declined: a warning when the pool has no `pr_agent_risk`. `test_the_risk_predicate_is_the_owner_decided_one` fails first, and diverging from the dotfiles script for a state that test forbids buys nothing.
  - Recorded in the runbook: the job runs the PR head's scripts with a second credential. This is the same trust class as the workflow file a `pull_request` run already takes from the head; forks and Dependabot are excluded.
  - Ticketed: the spec-verification guard reads only pytest-shaped commands, so the scaffold's `echo` escaped it (#2308, TOOL-119).
  - Declined: the `dotf spec check` mismatch. dotfiles' AGENTS.md lists `check` among the conversational steps the `/spec` skill drives, not among the `dotf spec` subcommands, and the skill says it has no CLI fallback yet. The docs and the binary agree.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ci-automation/lesson-575-a-pr-agent-toml-provider-applies-to-every-model.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? yes: docs/adr/adr-070-review-pool-adopts-dotfiles-adr-046.md
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: the pool design is dotfiles' ADR-046, already shared through TOOL-117 (#2295), and a second pattern would repeat it

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-082-pr-agent-review-pool/` -> `specs/archive/TOOL-082-pr-agent-review-pool/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
