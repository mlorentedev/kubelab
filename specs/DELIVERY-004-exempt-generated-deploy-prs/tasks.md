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

- [ ] [AC4] Golden test on the `mechanical` declaration; mutation proof per field.
- [ ] [AC5] Prod unreachable: predicate refuses prod files and semver tags; declaration admits only `staging`.

## PR 3 — the merge step, switch off (AC6)

- [ ] [AC6] Merge job: recompute, `gh pr merge --squash --match-head-commit`, `RELEASE_PLEASE_TOKEN`, switch default off.
- [ ] [AC4] Tests pin the job's `if:` and merge command.

## PR 4 — the flip (AC7)

- [ ] Preconditions linked on #1619, then flip. Rollback = revert.

## Closing

- [ ] [AC8] Reviewer quota measurement posted on #1619.
- [ ] Follow-up on dotfiles#2836: swap the PAT for the App.
- [ ] Gap on the prod signature recorded on #1741.
- [ ] Independent adversarial review before archive.
