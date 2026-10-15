---
tags: [spec, verification, templates]
created: "2026-10-14"
---

# Verification - TOOL-082-pr-agent-review-pool

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] **AC1**: `tests/test_reviewer_pool.py` (vendor, credential path, amendment B, draw and route shape, risk predicate) and `test_every_model_pr_agent_reviews_with_is_admitted_in_the_reviewer_pool`, now matched on `pr_agent.model`. The CLI enforces amendment B on load, measured 2026-10-15 with dotf at the commit that added the pool:
  - `dotf spec review TOOL-082-pr-agent-review-pool --dry-run --reviewer anthropic-review/claude-haiku-5-5` is refused with `it is a fallback, which signs first only when the first signers failed: pass --fallback-reason`;
  - the same with `--fallback-reason quota` builds the launch command;
  - `--reviewer nan/glm5.3-flash` builds the launch command.
  - `--reviewer agy/gemini-3.8-flash-high` builds `agy --model gemini-3.8-flash-high ...` with no `--provider` flag and no `dotf secrets run --only` wrapper. That is the `auth: login` path, so the arm launches without the key it used to name (#2298 review).

  `test_another_vendor_can_sign_first` holds the other half of amendment B: a first signer from outside Anthropic exists.

  ADR: `docs/adr/adr-070-review-pool-adopts-dotfiles-adr-046.md`.
- [ ] **AC2**: pending (PR 2)
- [ ] **AC3**: pending (PR 2)
- [ ] **AC4**: pending (PR 2, PR 3)
- [ ] **AC5**: pending (PR 3, live)
- [ ] **AC6**: pending (PR 3, live)

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- The pool is dotfiles' file transformed, not rewritten:
  - dotfiles issue numbers are qualified as `mlorentedev/dotfiles#N`, and dotfiles-only paths are prefixed `dotfiles`;
  - a header records the source commit;
  - kubelab's own deepseek measurement (#1205) is kept.

  Rewriting the admission records by hand would have produced a third version of the same facts.
- The WIP gate refused a new spec (16 active against a limit of 10). The owner overrode it on 2026-10-15; the reason is recorded as `wip_override` in `proposal.md`.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-082-pr-agent-review-pool/` -> `specs/archive/TOOL-082-pr-agent-review-pool/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
