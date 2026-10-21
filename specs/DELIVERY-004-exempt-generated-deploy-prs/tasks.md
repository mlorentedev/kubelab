---
tags: [spec, tasks]
created: "2026-09-04"
---

# Tasks - DELIVERY-004-exempt-generated-deploy-prs

> TDD order. Manu merges every PR in this lane. Draft while iterating, `gh pr ready`
> once. Each PR gets a `## Review triage` comment.

## Setup

- [x] Operator decision recorded on #1619 ✓ 2026-10-21 (dated 2026-10-20)
- [x] Proposal rewritten against (a)-(d) ✓ 2026-10-21
- [x] Coordinated: IDP-042 (no receiver change), GITOPS-003 (switch gated on its PR 2 and #2584) ✓ 2026-10-21

## PR 1 — `deploy-shape`, assert-only (AC1, AC2, AC3 declaration)

- [x] [AC1] Failing tests for the pure predicate: each of the four conditions refused on its own; #2576/#2581 shapes accepted; contract-change shape and prod files refused.
- [x] [AC1] `toolkit/features/deploy_shape.py`: pure `classify()` + an API reader (gh) that fails closed.
- [x] [AC2] `mechanical` block in `harness/review-attestation.json`; extend the no-policy-in-module test to both modules.
- [x] [AC1] `toolkit tools deploy-shape` CLI: JSON verdict, exit 0 mechanical / 1 not mechanical / 2 unknown.
- [x] [AC1] `.github/workflows/deploy-shape.yml`: master's code, check-run `success`/`neutral`/`failure`.
- [x] [AC2] `review-attestation`: drop the file-only staging signature; exempt on a recomputed `mechanical` at the attested head sha.
- [ ] [AC3] Measure a neutral run against protection on a real PR, then add `deploy-shape` to `required_contexts` (operator reconciles live).
- [x] Lesson in `docs/lessons/` (lesson-610) ✓ 2026-10-21

## PR 2 — widening tests (AC4, AC5)

- [x] [AC4] Golden test on the `mechanical` declaration; mutation proof per field ✓ 2026-10-21
- [x] [AC5] Prod unreachable: predicate refuses prod files and semver tags; declaration admits only `staging` ✓ 2026-10-21

## PR 3 — the merge step, switch off (AC6)

Design recorded 2026-10-21; not built in the run that wrote it, because it was outside that
run's envelope. The operator approves this design before it is built.

- [ ] [AC6] `toolkit tools deploy-merge --pr N`, tested against a fake API like `evaluate()`. The
  workflow stays thin. It refuses unless all of these hold at one head sha read once, and re-read
  before merging:
  - the switch is on (a `merge` key in the `mechanical` block);
  - `evaluate()` says `mechanical`;
  - every context in `ci.branch_protection."mlorentedev/kubelab".master.required_contexts` (read from
    common.yaml, never hardcoded) reports success / neutral / skipped on that sha, checking both
    commit statuses (`review-attestation` is one) and check-runs;
  - `mergeable_state == clean`.
  Then exactly `gh pr merge N --squash --match-head-commit <sha>`. A `--match-head-commit`
  refusal means the receiver force-pushed mid-run: report it as superseded, exit 0.
- [ ] [AC6] Identity: `RELEASE_PLEASE_TOKEN` on the merge step only, so push workflows fire after the
  merge (`check-config-drift`, `ci`, `ci-cleanup`, `release`, `repo-hygiene`); reads use
  `GITHUB_TOKEN`. Measured 2026-10-21: `enforce_admins` is `true` and approvals required are `0`, so
  the owner's PAT is gated by the required checks and needs no approval. The job's own checks are
  still the primary gate.
- [ ] [AC6] Trigger: enumerate open non-draft PRs against master and judge each one. Never read the
  event payload, which sidesteps #1184's context loss and keeps branch names out of the grant.
  `workflow_run` on the required workflows completing, plus a schedule sweep and `workflow_dispatch`.
  One repo-wide concurrency group, `cancel-in-progress: false`.
- [ ] [AC4] `MERGERS` in `tests/test_deploy_shape_widening.py` gains the workflow and its single merge
  line. When PR 3 adds the `merge` key, `test_no_field_was_added` goes red, and when PR 4 flips it,
  `test_each_field_is_the_approved_one` goes red. That is the design: each change to the switch is
  one reviewed diff of the test and the declaration together. Never "fix" the test alone.
- CI workflow path, so it is never landed under a standing grant.

## PR 4 — the flip (AC7)

- [ ] Preconditions linked on #1619, then flip. Rollback = revert.

## Closing

- [x] [AC8] Reviewer quota measured 2026-10-21: on #2576 and #2581 CodeRabbit ran a full review ("No actionable comments"), and Codex attempted one and hit its usage limit. Both still spend quota on deploy PRs. pr-agent skips them. Posted on #1619.
- [ ] Follow-up on dotfiles#2836: swap the PAT for the App.
- [ ] Gap on the prod signature recorded on #1741.
- [ ] Independent adversarial review before archive.
