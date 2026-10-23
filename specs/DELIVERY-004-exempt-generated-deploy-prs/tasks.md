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
- [x] Lesson in `docs/lessons/` (lesson-613) ✓ 2026-10-21

## PR 2 — widening tests (AC4, AC5)

- [x] [AC4] Golden test on the `mechanical` declaration; mutation proof per field ✓ 2026-10-21
- [x] [AC5] Prod unreachable: predicate refuses prod files and semver tags; declaration admits only `staging` ✓ 2026-10-21

## PR 3 — the merge step, switch off (AC6)

Design recorded 2026-10-21, approved by the operator 2026-10-22 with two additions: close
empty deploy PRs instead of merging them, and pin the merge to the judged head sha.

- [x] [AC6] `toolkit tools deploy-merge`, a judge tested against a fake API like `evaluate()`
  (`tests/test_deploy_merge.py`, each condition refused alone). It writes decisions and never
  merges. A PR is merged only when, at one head sha read first and re-read last:
  - `evaluate()` says `mechanical`;
  - every context in `ci.branch_protection."mlorentedev/kubelab".master.required_contexts` (read
    from common.yaml) passes on that sha, every reporter of it (status and check-run alike, the
    latest run of a check) and none missing;
  - `mergeable_state == clean`.
  The switch is `mechanical.merge`; only the boolean `true` is on, and `load_declaration` ignores
  the key, so a malformed switch never turns deploy-shape red. Deviation from the design: the
  command enumerates the open PRs itself (REST, not GraphQL) instead of taking `--pr N`, since every
  trigger enumerates. ✓ 2026-10-22
- [x] [AC6] Empty PRs: a non-draft PR with no changed files is closed with a comment, behind the same
  switch. It is a content rule, so it closes any such PR, not only the receiver's; reopening undoes
  it. "Superseded" closes nothing: the receiver keeps one long-lived PR per app, so a newer tag is
  a head move, which `--match-head-commit` refuses and the next run judges. ✓ 2026-10-22
- [x] [AC6] Identity: `RELEASE_PLEASE_TOKEN` on the merge step only, so push workflows fire after the
  merge; reads and the close use `GITHUB_TOKEN`. A test pins both. ✓ 2026-10-22
- [x] [AC6] Trigger: `workflow_run` on CI, review-attestation and deploy-shape completing, a
  schedule sweep, and `workflow_dispatch`. One repo-wide concurrency group,
  `cancel-in-progress: false`. With the switch off, each run reports what it would do; that report
  is the evidence PR 4 links. ✓ 2026-10-22
- [x] [AC4] `MERGERS` gains `deploy-merge.yml` and its single merge line; `APPROVED` gains
  `merge: false` in the same diff as the registry. ✓ 2026-10-22
- Not a per-PR condition: the `argocd/kubelab-staging` status. Staging gets no status while ace1 is
  off or the slot is repointed (deploy-verify.yml header), so the merger would block most of the
  day. Green deploy-verify runs are PR 4's precondition, linked on #1619.
- CI workflow path, so it is never landed under a standing grant.

## PR 4 — the flip (AC7)

- [ ] Preconditions linked on #1619, then flip. Rollback = revert.

## Closing

- [x] [AC8] Reviewer quota measured 2026-10-21: on #2576 and #2581 CodeRabbit ran a full review ("No actionable comments"), and Codex attempted one and hit its usage limit. Both still spend quota on deploy PRs. pr-agent skips them. Posted on #1619.
- [ ] Follow-up on dotfiles#2836: swap the PAT for the App.
- [ ] Gap on the prod signature recorded on #1741.
- [ ] Independent adversarial review before archive.
