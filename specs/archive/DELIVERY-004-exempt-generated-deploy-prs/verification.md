---
tags: [spec, verification, templates]
created: "2026-09-03"
---

# Verification - DELIVERY-004-exempt-generated-deploy-prs

## Evidence

- AC1 (PR 1): `tests/test_deploy_shape.py` (38 tests). Live, 2026-10-21, `toolkit tools deploy-shape --pr N`:
  - #2581 exit 0 `mechanical`: web sha-f55a8c0 -> sha-9d79e52, head `5f8dec3e`
  - #2576 exit 0 `mechanical`: web sha-7ebd808 -> sha-f55a8c0, head `cfa843dd`
  - #2579 (human PR) exit 1 `not-mechanical`: file set
- AC2 (PR 1): `tests/test_review_attestation.py` (`test_the_staging_files_alone_no_longer_exempt`,
  `test_a_mechanical_verdict_at_the_head_sha_exempts`, `test_any_other_verdict_does_not_exempt`,
  `test_no_reviewer_is_named_in_the_module` extended to both modules).
- Mutation proofs (`make mutate`, each RED): `len(values) != 1` -> `< 1`; exact file set -> subset;
  attestation head-sha equality -> `True`; provenance compare -> `False`. The first one survived until
  `test_a_change_after_the_version_ends_it_too` was added.

- AC4/AC5 (PR 2): `tests/test_deploy_shape_widening.py`. `make mutate`, each RED: `tag_pattern` -> `{7,}` unbounded;
  `env` -> `prod`; an extra key in `mechanical`; a `gh pr merge` line in a workflow not declared in `MERGERS`.

- AC6/AC7 (PR 3, #2656, switch off): `tests/test_deploy_merge.py` and the widening test. The follow-ups were
  #2888 (scope the default-branch guard to dispatch), #2898 (correct the guard comment to the measured payload)
  and #2910 (accept `unstable` when every required context is green, after #2883 was skipped as `unstable`).
  #2910 is proven by `test_an_unstable_pr_with_every_required_context_green_merges` and
  `test_unstable_does_not_excuse_a_red_required_context`. The widening test pins `MERGE_STATES_OK`.
- Dry-run evidence (switch off, operator N = 3, four cases), logged on #1619 (issuecomment-6591928848):

  | PR | Bump | Judged `merge` at | Merged by hand | Deploy-verify |
  |---|---|---|---|---|
  | #2948 | api sha-80171ff | 62549f5a | 898ede99 | 41396476626 (shared with #2949) |
  | #2949 | web sha-4b395ac | af6992aa | 3752be80 | 41396476626 success |
  | #3007 | api sha-75346a3 | 990a6c42 | dc979461 | 41477835222 success |
  | #2967 | web sha-95588df | cabf5469 | 5d43b172 | 41496856210 success |

  No false positives; #2967 was judged `skip` at three earlier heads while a required context was not green.
- #2983 (review Major 2, #3022): `unstable` excuses only `ALLOWED_UNSTABLE = {"add-to-project"}`, and the moved
  image must belong to the container named after the bumped app. All four cases stay `mechanical` under it.
- AC7 (PR 4): `mechanical.merge` flipped to `true`; the widening test's `APPROVED` and
  `TestSwitch.test_the_committed_switch_is_on` move with it. `make mutate` back to `false`: RED.
- First unattended merge (#1619 issuecomment-6620340511): deploy-merge run 41673134991 judged `#3056 merge at 497c50da`
  (api sha-b392e87) and merged it as f3478fab; deploy-verify 41673297336 and 41673422777 passed on it. The same run
  skipped #3055 as `not-mechanical`. All 30 deploy-verify runs since the flip succeeded.
- Review-2 (`review-2.md`, FAIL on three Majors, no Blocker), fixed in one PR. Each mutation RED:
  - F1: every checkout in deploy-merge, deploy-shape and review-attestation pinned to the default branch
    (deploy-merge's made explicit), and each judge invocation pinned. Mutants: `workflow_run.head_sha` ref,
    `pull_request.head.sha` ref on both others, `--registry /dev/null`.
  - F2: the granting modules read no head ref, author or `deploy/` prefix (code only, AST); a `deploy/staging-web`
    PR by the bot with a non-mechanical diff is skipped. Mutant: a `deploy/` ref bypass in `judge()`.
  - F4: master's `required_contexts` pinned. Mutant: dropping `Tests`.
  - F3: the PR bodies and headers no longer say an open PR holds staging; the runbook
    (`docs/runbooks/gitops-delivery-promotion.md`) documents the hold (draft) and the stop (disable, then revert).
- Review finding Major 1 (#2982): pins the merge and close feeds, the triggers and the token scope of
  `deploy-merge.yml`. Each of these edits goes RED under `make mutate`: `select(.action == "merge")` ->
  `!= "skip"`; `.head_sha` -> `.pr`; `contents: read` -> `write`; the cron changed. The review's two untested guards
  are covered in the same PR, and each goes RED: `evaluate()`'s `base_ref != default_branch` -> `False`, and
  dropping `or shape.head_sha != head` from `judge()`.

## Test status

- PR 1: `make test` 6406 passed, 2 failed before fixes (pinned `gh pr view` field list, stale toolkit README); both fixed, targeted rerun green.
- Review-2 fixes (2026-11-03): the DELIVERY-004 suites plus the receiver tests, 247 passed.

## Decisions made during implementation

- Operator 2026-10-21: attestation adopts the content predicate in PR 1; every registry app is in the class (api proven against this repository); names `deploy-shape`.
- Check-run, not commit status: only a check-run can answer `neutral` for a normal PR.
- Consumers recompute from master's code; the check is visible, not authoritative.
- Traceability (final review, Minor): `features.json` breaks out only f1 and f2 (AC1, AC2). AC3–AC8 are proven in the Evidence section above and stay unlisted there, because the review's contract digest froze `features.json`.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ci-automation/lesson-613-an-exemption-keyed-on-which-files-changed-exempts-whatever-those-files-say.md, docs/lessons/ci-automation/lesson-699-unstable-stops-enforcing-every-check-not-required.md, docs/lessons/ci-automation/lesson-711-an-anchored-pattern-and-python-equality-both-admit-more-than-they-read.md
- [x] ADR-worthy decision? yes: docs/adr/adr-037-environment-promotion-strategy.md (its "leaving the PR open holds staging" no longer holds for staging; amended)
- [x] New pattern candidate? no: the "diff nobody wrote" rule already lives in the global harness.

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/DELIVERY-004-exempt-generated-deploy-prs/` -> `specs/archive/DELIVERY-004-exempt-generated-deploy-prs/`
- [x] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018): #1619 closes with the archive PR. ✓ 2026-11-05
- [x] Promotions above executed (if any)
