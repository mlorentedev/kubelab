---
spec: "DELIVERY-004-exempt-generated-deploy-prs"
verdict: "PASS"
reviewed_sha: "9277d6d09446b39c685b5ce77ab57f6b294825a0"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-11-05"
---

## Adversarial review

**Scope**: DELIVERY-004-exempt-generated-deploy-prs (#1619) across the entire scope `git diff b01818b1d95d272059fd64a836f0b34c9ff7604f...HEAD` (reviewed commit `9277d6d09446b39c685b5ce77ab57f6b294825a0`).
**Sources**:
- Spec contract: `specs/DELIVERY-004-exempt-generated-deploy-prs/{proposal.md,tasks.md,verification.md,features.json,review-round1.md,review-2.md}`
- Core implementation: `toolkit/features/deploy_shape.py`, `toolkit/features/deploy_merge.py`, `toolkit/features/review_attestation.py`
- Workflows & configs: `.github/workflows/{deploy-merge.yml,deploy-shape.yml,review-attestation.yml,product-image-receiver.yml,staging-deploy.yml,deploy-verify.yml}`, `harness/review-attestation.json`, `infra/config/values/common.yaml`
- Documentation: `docs/runbooks/gitops-delivery-promotion.md`, `docs/adr/adr-037-environment-promotion-strategy.md`
- Test suites: `tests/test_deploy_shape.py`, `tests/test_deploy_merge.py`, `tests/test_deploy_shape_widening.py`, `tests/test_review_attestation.py`, `tests/test_no_auto_merge.py`, `tests/test_deploy_impersonation.py`, `tests/test_deploy_verify_workflow.py`

**Independence**: Independent third-round review conducted by `agy/gemini-3.8-flash-high` drawn from `harness/reviewer-pool.json`. Neither this model nor this runner authored the implementation or prior reviews.

**Evidence executed this session**:
- Unit & widening suite: `./.venv/bin/pytest -p no:cacheprovider -q --no-cov tests/test_deploy_shape.py tests/test_deploy_merge.py tests/test_deploy_shape_widening.py tests/test_review_attestation.py tests/test_no_auto_merge.py`: 253 passed in 1.51s.
- Extended delivery suite: `./.venv/bin/pytest -p no:cacheprovider -q -m "not e2e and not infra and not integration" --no-cov tests/test_deploy* tests/test_review* tests/test_no_auto_merge*`: 319 passed in 1.51s.
- Cyclomatic complexity: `./.venv/bin/ruff check --no-cache --select C901 toolkit/features/deploy_*.py`: clean, max-complexity <= 10 strictly enforced via `pyproject.toml` per-file inclusion.
- Mutation probes (scratchpad harness executing against target file, verified red, then clean file restore):
  1. *Judge checkout ref (F1)*: In `.github/workflows/deploy-merge.yml`, mutated `ref: ${{ github.event.repository.default_branch }}` to `ref: ${{ github.event.workflow_run.head_sha }}` -> RED (`TestTheJudgeIsMasters::test_every_checkout_is_the_default_branch[deploy-merge.yml] FAILED`).
  2. *Deploy shape checkout ref (F1)*: In `.github/workflows/deploy-shape.yml`, mutated `ref: ${{ github.event.repository.default_branch }}` to `ref: ${{ github.event.pull_request.head.sha }}` -> RED (`TestTheJudgeIsMasters::test_every_checkout_is_the_default_branch[deploy-shape.yml] FAILED`).
  3. *Branch name grant (F2)*: In `toolkit/features/deploy_merge.py`, injected `if (shape.verdict != MECHANICAL and not pr["head"].get("ref", "").startswith("deploy/"))` -> RED (`test_the_granting_side_reads_no_branch_name_or_author[toolkit/features/deploy_merge.py] FAILED`).
  4. *Required contexts set (F4)*: In `infra/config/values/common.yaml`, deleted `- Tests` from master's `required_contexts` -> RED (`test_the_required_contexts_are_the_approved_ones FAILED`).
  5. *Judge command arguments (F1)*: In `.github/workflows/deploy-merge.yml`, appended `--registry /dev/null` to the deploy-merge CLI invocation -> RED (`TestTheJudgeIsMasters::test_the_judge_runs_with_its_declared_arguments[deploy-merge.yml] FAILED`).
- Live operational verification:
  Unattended merges have landed repeatedly in production git history post-flip without regression (#3056, #3083, #3093, #3094, #3095, #3099, #3109, #3120, #3125), while non-mechanical PRs are reliably skipped.

### Spec and task alignment

- **AC1 (a)**: Verified. `deploy-shape` strictly classifies diffs (`classify_diff`), requiring exact declared file sets (`staging.yaml` and `deployments.yaml`), single leaf version move to `^sha-[0-9a-f]{7,40}$`, matching overlay container image move, and default-branch commit provenance. Read/parse failures fail closed as `unknown`. Covered by 54 tests in `tests/test_deploy_shape.py`.
- **AC2 (c)**: Verified. The `mechanical` class is declared in `harness/review-attestation.json` and neither module hardcodes paths. `review_attestation.py` exempts staging deploy only on recomputed `mechanical` verdict at verified head SHA. Tested by 54 tests in `tests/test_review_attestation.py`.
- **AC3 (a)**: Verified. `deploy-shape` is committed as a required context in `infra/config/values/common.yaml` and reconciled live on master branch protection.
- **AC4 (c)**: Verified. Widening tests in `tests/test_deploy_shape_widening.py` comprehensively guard the declaration, triggers, permissions, step order, checkout refs, CLI invocation arguments, and AST scans preventing branch-name grants. All 5 mutation probes executed in this session went RED.
- **AC5 (d)**: Verified. Predicate rejects `values/prod.yaml`, prod overlay, and semver tags. Pinned in unit tests.
- **AC6 (b)**: Verified. Merges use `gh pr merge --squash --match-head-commit <sha> --subject <subject> --body <body>` under `RELEASE_PLEASE_TOKEN` with `allow_auto_merge: false` continuously asserted by `test_no_auto_merge.py`.
- **AC7**: Verified. Gated switch flipped in commit `d445ba2a` (#3038) after verifying dry-run evidence on #1619. Post-flip unattended merges have landed cleanly.
- **AC8**: Verified. CodeRabbit/Codex quota impact measured and posted to #1619.

### Adversarial refutation of past findings (Round 2 closure audit)

1. **R2 F1 (Judge checkout ref and CLI arguments unpinned - Major, REAL)**:
   - *Status*: RESOLVED in commit `3950b28f` (#3063).
   - *Audit*: `TestTheJudgeIsMasters` in `tests/test_deploy_shape_widening.py` pins default branch checkouts across `deploy-merge.yml`, `deploy-shape.yml`, and `review-attestation.yml`, pins prelude steps, forbids reswapping/env injection commands, and asserts exact judge CLI arguments. Proved RED under mutation.
2. **R2 F2 (Branch name grant absent guard test - Major, REAL)**:
   - *Status*: RESOLVED in commit `3950b28f` (#3063).
   - *Audit*: `_granting_code()` parses AST of `deploy_merge.py`, `deploy_shape.py`, and `review_attestation.py` (exemption path) and asserts no branch name (`head_ref`, `deploy/*`, `ref`, etc.) or author keys are read. Positive control `test_the_name_detector_fires` passes. Proved RED under mutation.
3. **R2 F3 (Documented hold for staging false - Major, REAL)**:
   - *Status*: RESOLVED in commit `3950b28f` (#3063).
   - *Audit*: `docs/runbooks/gitops-delivery-promotion.md` documents "Hold or stop unattended staging merges" (draft PR hold, `gh workflow disable deploy-merge.yml`, `mechanical.merge` switch). `docs/adr/adr-037-environment-promotion-strategy.md` amended. Obsolete hold strings in `.github/workflows/product-image-receiver.yml` and `.github/workflows/staging-deploy.yml` replaced with draft hold guidance.
4. **R2 F4 (`required_contexts` in common.yaml unpinned - Minor, THEORETICAL)**:
   - *Status*: RESOLVED in commit `3950b28f` (#3063).
   - *Audit*: `test_the_required_contexts_are_the_approved_ones` asserts the exact 5 contexts (`Validate`, `Detect Changes`, `review-attestation`, `Tests`, `deploy-shape`). Proved RED under mutation.
5. **R2 F5 (`_leaves` type equality & tag regex pinning - Minor, SPECULATIVE)**:
   - *Status*: RESOLVED in commit `bfaa871a` (#3101).
   - *Audit*: `_leaves()` checks `(type(before), before) == (type(after), after)` so YAML type mutations are tracked. `decl.tag_pattern.fullmatch` strictly enforced.
6. **R2 F6 (Squash message unjudged - Minor, THEORETICAL)**:
   - *Status*: RESOLVED in commit `bfaa871a` (#3101).
   - *Audit*: `deploy_merge.py:215-216` generates `--subject` and `--body` explicitly from the judged app and tag (`chore(staging): deploy {shape.app} {shape.new} (#{number})`). PR title and body are ignored.
7. **R2 F7 (Close step starving merge step - Minor, THEORETICAL)**:
   - *Status*: RESOLVED in commit `bfaa871a` (#3101).
   - *Audit*: `deploy-merge.yml` runs close loop with `set +e`, sets `steps.close.outputs.failed`, and reports close failure in a deferred step (`Fail on a refused close` with `if: always() && steps.close.outputs.failed == 'true'`) after the merge step executes.
8. **R2 F9 (Cyclomatic complexity of `classify_diff` - Minor, REAL)**:
   - *Status*: RESOLVED in commit `bfaa871a` (#3101).
   - *Audit*: `classify_diff` refactored into focused helpers (`_file_set_refusal`, `_changed_leaves`, `_version_move`, `_overlay_refusal`). `pyproject.toml` explicitly enforces C901 (threshold <= 10) on all `deploy_*.py` modules without exception.
9. **R2 F11 (Circuit breaker when deploy-verify is red - Question / Operational)**:
   - *Status*: RESOLVED in commit `22fa8376` (#3086).
   - *Audit*: `pause_reason()` in `toolkit/features/deploy_merge.py` inspects completed runs of `deploy-verify.yml` on master. If the latest staging verdict is not green, or cannot be read, or is absent in the last 100 runs, every PR is skipped. Tested in `tests/test_deploy_merge.py`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | Spec tracking | `features.json` lists f1 and f2 only (AC1, AC2) with `state: passing`; AC3–AC8 are tracked and proven in `verification.md` and `proposal.md` but not broken out as separate items in `features.json`. Modifying `features.json` post-request is prohibited to preserve contract digest integrity. | `features.json` contents | n/a | spec (`verification.md` disposition; leave `features.json` frozen) |
| Minor | THEORETICAL | Identity audit | Merges made under `RELEASE_PLEASE_TOKEN` show the operator's personal login as `merged_by` on the PR UI and git log. | Known constraint documented in proposal and tasks | `tests/test_deploy_merge.py` | tracked on `mlorentedev/dotfiles#2836` (SEC-017) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | Every AC is satisfied, negative paths are covered, all prior review gaps are refuted, and live unattended merges run cleanly. |
| Verification       | A | 253 delivery suite tests and 319 extended tests pass; 5 live mutation probes proved RED; operational log evidence confirms behavior. |
| Scope              | A | Strict boundary maintained: prod is unreachable, receiver is untouched, and #1741 is left to its own lifecycle. |
| Reliability        | A | Fail-closed error handling, `--match-head-commit` TOCTOU prevention, deploy-verify circuit breaker, and decoupled close/merge steps. |
| Maintainability    | A | Modular pure functions with C901 complexity <= 10 strictly enforced by ruff; clear AST-based widening guards. |
| Handoff-readiness  | A | Comprehensive runbook section, amended ADR-037, aligned receiver PR bodies, and recorded lessons (613, 699). |

### Verdict
PASS

### Recommended next steps

The change meets the full Definition of Done and satisfies all operator requirements (a)-(d). All contract-set files (`proposal.md`, `tasks.md`, `features.json`) are frozen and match their request digests.

1. Record final dispositions for the two minor findings in `verification.md`:
   - Feature granularity: AC3-AC8 are fully evidenced in `verification.md`; `features.json` left untouched to protect contract digest.
   - App identity: continue tracking on `mlorentedev/dotfiles#2836` (SEC-017).
2. Proceed with spec archival via `dotf spec archive DELIVERY-004-exempt-generated-deploy-prs`. Archival is **advisable** in the current state.
