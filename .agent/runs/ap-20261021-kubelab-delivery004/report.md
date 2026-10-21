# Run ap-20261021-kubelab-delivery004: report

Objective: DELIVERY-004 (#1619) PR 1 (`deploy-shape`, assert-only) and PR 2 (widening tests) opened
ready for the operator's merge, with triage and lessons. Envelope: `merge: never`.

## Waiting on the operator, in order

1. **Merge #2593** (PR 1). `deploy-shape` is red on its own head by construction: the workflow runs
   master's toolkit, which does not have the command yet. Disclosed in the PR body. The first PR
   opened after the merge shows the real verdict.
2. **Rebase #2596** (PR 2, stacked on #2593) onto master, then `gh pr ready 2596`.
3. **AC3:** once a `neutral` run of `deploy-shape` is seen passing protection on an ordinary PR,
   add `deploy-shape` to `ci.branch_protection` required contexts in `common.yaml` and reconcile.
4. **Approve or amend the PR 3 design** (merge step, switched off). It lives in the spec's
   `tasks.md` on `feat/delivery-004-widening-tests`. It was not built: it is outside this envelope,
   and the flip waits on GITOPS-003's `deploy-verify.yml` and #2584 regardless.
5. **Adversarial review** by someone other than the implementer, before the spec archives.

## Done

- #2593 PR 1: `toolkit/features/deploy_shape.py`, the `deploy-shape` check-run, the `mechanical`
  class in `harness/review-attestation.json`, and an attestation that exempts only on a mechanical
  verdict at the head sha. 38 tests. Lesson 610.
- #2596 PR 2: `tests/test_deploy_shape_widening.py`, which pins the class field for field, pins
  every workflow merge call, and asserts that prod is unreachable.
- Live verdicts: #2581 and #2576 `mechanical`, #2579 `not-mechanical`.
- Mutation proofs, all red: values count, exact file set, attestation head-sha equality,
  provenance compare, unanchored tag pattern, env set to prod, extra key, undeclared
  `gh pr merge`.
- AC8 measured and posted on #1619 (issuecomment-6319673421): CodeRabbit spends a full review on
  every deploy PR and Codex attempts one. Neither can be scoped to the predicate from the repo.
- The prod file-only exemption gap is noted on #1741 (issuecomment-6319264541), not fixed (out of
  bounds).
- SEC-017 follow-up posted on dotfiles#2836 (issuecomment-6319703866): the merge step's
  `RELEASE_PLEASE_TOKEN` moves to the App identity.

## Disclosures

- `toolkit/README.md` was regenerated (`toolkit tools cli-reference --write`) because the new
  `deploy-shape` command changes the generated CLI reference. That file is outside the envelope's
  `write_paths`; the change is generated output only.
- No merge, no deploy, no change to `product-image-receiver.yml`, `promote-prod.yml`, or any values
  file.
- Host: no wake-lock was armed (`caffeinate -i -t 21600` was not run), so the window is covered only
  while the host stayed awake.
- The repo-wide triage queue lists PRs of peer sessions (#2590, #2591, #2592, #2595), not this lane's.
