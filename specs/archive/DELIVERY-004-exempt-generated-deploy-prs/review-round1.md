---
spec: "DELIVERY-004-exempt-generated-deploy-prs"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "f58c2cbe3ebcf8a64703f999665d1f921e7081f8"
reviewer: "claude-sonnet-5-5"
date: "2026-11-02"
---

## Adversarial review

**Scope**: DELIVERY-004 (#1619), PRs 1-3 as on master at f58c2cbe, switch `mechanical.merge` still false. PR 4 (the flip, AC7) is not in scope and is not done.
**Sources**: `specs/DELIVERY-004-exempt-generated-deploy-prs/{proposal,tasks,verification,features.json}`; `toolkit/features/deploy_shape.py`, `deploy_merge.py`; `deploy-merge` and `deploy-shape` commands in `toolkit/cli/tools.py`; `.github/workflows/deploy-merge.yml`, `deploy-shape.yml`, `review-attestation.yml`; `harness/review-attestation.json`; `tests/test_deploy_merge.py`, `test_deploy_shape.py`, `test_deploy_shape_widening.py`. Live reads: branch protection of master, open PRs #2966-#2968.
**Independence**: I did not implement this. Reviewer model family is stated in the frontmatter; if the pool requires a different vendor's first signature, that is for the launcher to check.

Evidence run this session:
- `poetry run pytest -q --no-cov tests/test_deploy_merge.py tests/test_deploy_shape.py tests/test_deploy_shape_widening.py`: 108 passed.
- `toolkit tools deploy-merge --repo mlorentedev/kubelab --out <scratch>` against the live repo (writes decisions only, merges nothing): #2966, #2967, #2968 (staging deploy PRs) -> `merge ... every required context passing; clean`; all 12 other open non-draft PRs -> `skip: not-mechanical: the changed files are not exactly ...`; draft -> `skip: a draft`. The judge discriminates correctly on real data.
- Live protection: `enforce_admins: true`, required contexts exactly `Validate, Detect Changes, review-attestation, Tests, deploy-shape`, each with `app_id 15368`; `allow_auto_merge: false`; repo is public.
- `make mutate` runs, listed per finding below.

### Spec and task alignment

- `proposal.md` and `tasks.md` exist and are consistent; `verification.md` exists but its "Test status" and "Evidence" stop at PR 2. It has no entry for PR 3 (the judge, the workflow, the `unstable` amendment), and its "Promotion candidates" and "Archive checklist" are unfilled template text. `features.json` lists f1 and f2 only (AC1, AC2); AC4-AC6 have no feature entry and both entries are `state: pending`, `evidence: ""`.
- AC1 (a): holds. Each condition is refused alone in `tests/test_deploy_shape.py`; any API or parse failure is `unknown` (`deploy_shape.py:244-270`); the head is read before and after.
- AC2 (c): holds. The file-only staging signature is gone from the exempt list; `review_attestation.py:262-267` exempts only on `mechanical` with `head_sha == headRefOid`; both modules name no path (test exists). Note the workflow runs from the PR and the toolkit from master, so the status is forgeable by a same-repo PR, but a forged status cannot make a PR mechanical for the merger, which recomputes.
- AC3: done per tasks.md; live protection confirms `deploy-shape` is required.
- AC4 (c): only partly holds. See F1.
- AC5 (d): holds in effect (file set excludes prod, tag pattern excludes semver), but see F5 (`env` is decorative).
- AC6 (b): holds. One merge line pinned with `--match-head-commit`, steps gated on the judged switch, PAT confined to the merge step (test), `allow_auto_merge=false`.
- AC7: not met, correctly: PR 4 has not happened. The proposal text still says `deploy-verify.yml` is "missing"; it exists on master (`.github/workflows/deploy-verify.yml`).
- AC8: recorded in tasks.md; I did not re-measure.

Attacks tried and refuted (the guard held):
- Not a pure staging single-app bump: file set is exact set equality plus `modified` only; the values diff must be exactly one leaf at `apps.platform.<registered app>.version` going to `^sha-[0-9a-f]{7,40}$`; overlay leaves must end in `image`, keep the repo, and move `old -> new`; extra YAML documents, list length changes, added keys, renames, multi-document values files are all not-mechanical or unknown. Mutants `app not in set(apps)`, `repo != repo_after`, `status` allow-list widening, `draft` check, `failing`, `conclusion not in _CHECK_OK`, final head re-read, second head re-read in `evaluate` all went RED.
- Branch name or author: neither is read anywhere in `deploy_shape.py`, `deploy_merge.py` or the CLI (grep); the workflow never touches the event payload.
- Prod reachable: no. Prod files are outside the exact file set, semver is outside the tag pattern.
- Head pushed after judging: `--match-head-commit "$sha"` with the judged sha; a moved head falls to the "superseded" branch. The close path re-reads the head before closing.
- Red context outvoted: statuses and check-runs are both checked, every reporter must pass, latest run of a name counts; verified RED on mutation.
- Pagination: file list capped at 100 cannot equal a 2-file set; open-PR enumeration pages to 50; live commit has 18 check-runs and 2 statuses, far under the 100 and 30 page limits; truncation of statuses/check-runs would read as "missing" (fail closed), except for the same-named red/green split (F6).
- API errors: every read is inside `try`, a failure is `unknown`/`skip`; a failed PR listing exits 2 before anything is judged.
- Pwn-request: the merge job checks out the default branch with no `ref:`, never reads PR-supplied code, and the dispatch guard is pinned by test.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location |
|----------|---------|------|---------|----------|---------------------------|--------------|
| Major | REAL | AC4 / criterion (c) | The merging workflow's selection of WHICH PRs the pinned merge line acts on is not pinned. `deploy-merge.yml:135` (`select(.action == "merge") \| "\(.pr) \(.head_sha)"`) can become `select(.action != "skip")` (feeds `close` decisions to `gh pr merge`) and the `$sha` source can be replaced (the judged sha is the entire head pin) with no test going red. Also unpinned: `schedule` cron (`:34`), `workflow_run.workflows` list (`:30`), `permissions:` block (`:41-45`, `contents: write` survives). The widening test pins only the literal `gh pr merge ...` line (`test_deploy_shape_widening.py:57,127-130`) and the two step `if:`s (`:132-144`). AC4 says tests fail if the merging job's `if:` or merge command changes; the condition that decides the merge set is neither. | `make mutate FILE=.github/workflows/deploy-merge.yml FROM='select(.action == "merge")' TO='select(.action != "skip")' TEST="tests/test_deploy_merge.py tests/test_deploy_shape.py tests/test_deploy_shape_widening.py"` -> `GREEN: the test passed against the mutant`. Same GREEN for `FROM='select(.action == "merge") \| "\(.pr) \(.head_sha)"' TO='... "\(.pr) \(.pr)"'` (sha source), for the cron, for `workflows: ['*']`, and for `contents: read -> write`. | UNTESTED (no named test covers the selection, sha source, triggers or permissions) | tests: extend `tests/test_deploy_shape_widening.py` to pin the merge loop's `done < <(jq ...)` selection and `read -r n sha` verbatim, plus `on:` and `permissions:` as parsed YAML |
| Major | THEORETICAL | `unstable` (#2910) | Accepting `unstable` also stops enforcing every non-required context on the PR. Live, those include `Drift / staging`, `Drift / prod` (the only generator-equals-values check, ADR-027), `GitGuardian Security Checks`, `Spec archive gate`, `hygiene`, `Sync check (Windows)`. The judge checks the five required ones only, so a PR the predicate calls mechanical but whose overlay disagrees with `generate(values)` merges with Drift red. The predicate does not rule that out: it accepts any non-empty subset of `image` leaves whose tag moves `old -> new` and never ties them to the bumped app's image (`deploy_shape.py:175-183`). A tag collision (api and web at the same `sha-` before a bump, plausible after a joint deploy) lets the overlay move the other app's image, which provenance never checked (it proves `new` against the bumped app's repo only). Today api and web carry different tags, so the path is not open, and the operator chose option B on #1619 knowing only the `add-to-project` case. The set is pinned (`MERGE_STATES_OK`); the premise "non-required failures do not matter" is not. | `gh pr checks 2967` lists `Drift / staging` and `Drift / prod` as non-required; protection lists five contexts. Judge comment `deploy_merge.py:12-13`. Test `test_an_unstable_pr_with_every_required_context_green_merges` covers only the benign case. | UNTESTED for "unstable with a failing Drift context" | code: accept `unstable` only when each failing non-required context is on a declared allow-list (e.g. `add-to-project`), or add `Drift / staging` to the judge's required set; also bind each changed overlay image to the bumped app's image repo. Tests accompany |
| Minor | REAL | Spec artifacts | `verification.md` has no PR 3 evidence, unfilled promotion/archive sections; `features.json` has no entries for AC4-AC6 and both entries are `pending` with empty evidence; `proposal.md` AC7 text says `deploy-verify.yml` is missing though it is on master. Contract-set note: edits to `proposal.md`/`features.json` invalidate this review; `verification.md` edits do not. | `cat verification.md`; `features.json`; `ls .github/workflows/deploy-verify.yml` | n/a | spec (verification.md now; contract-set files in the PR 4 round) |
| Minor | REAL | Supply chain | `deploy-merge.yml:66` pins `actions/setup-python@5fda3b95...` labelled `# v7`; 19 other workflows pin `6d4fd22b...` (the real `v7` tag, verified via the actions API). 5fda3b95 is a genuine but old commit ("Pin SHA commits ... #1338"), so the label is wrong. It is the one workflow that holds `RELEASE_PLEASE_TOKEN`. | `grep setup-python@ .github/workflows/*.yml` counts 1 vs 19; `gh api repos/actions/setup-python/git/ref/tags/v7` | UNTESTED | code: align the pin |
| Minor | REAL | AC5 | `Declaration.env` is read by nothing in `deploy_shape.py`/`deploy_merge.py` (grep for `.env` is empty); "the declaration admits only staging" is enforced by a path-string test (`test_the_class_is_staging_only`) and by the file set, not by the code. A future file-set edit that keeps "staging" in the path while pointing at a prod file would pass the test. | grep; `test_deploy_shape_widening.py:87-93` | `test_the_class_is_staging_only` (path substring only) | code or tests |
| Minor | REAL | Guard coverage | Two guards in the predicate are untested: `evaluate()`'s `base_ref != default_branch` (`deploy_shape.py:246`) and `judge()`'s `shape.head_sha != head` (`deploy_merge.py:122`; defence in depth, the final re-read covers it). Both mutants survived. `len(changes) != len(decl.files)` is an equivalent mutant (set equality already excludes duplicates). | `make mutate` GREEN for `if base_ref != default_branch:` -> `if False:` and for `or shape.head_sha != head` | UNTESTED | tests |
| Minor | THEORETICAL | Judge reads | `_failing_contexts` unions reporters by NAME across apps and takes the latest check-run id per name; the live protection pins `app_id 15368` per context. A green same-named check-run from another app could outvote a red one in the judge. GitHub's own enforcement at merge time (`enforce_admins: true`) backstops it, as does the page size (18 runs on a live sha vs the 100 limit). | `deploy_merge.py:84-99`; protection read | UNTESTED | code (compare `app.id`) |
| Minor | THEORETICAL | Empty-PR close | The close rule trusts `pulls/N/files == []`. A transient empty list on a freshly pushed head (diff not yet computed) would close a real PR. Mitigated: non-draft only, head re-read before closing, comment says reopen undoes it. | `deploy_merge.py:118`, workflow `:105-117` | `test_an_empty_pr_is_closed` (happy path only) | tests / consider requiring the same empty answer on two reads |
| Minor | THEORETICAL | Merge identity | Squash-merge message and title come from the PR and are not judged; a human or fork author could put `[skip ci]` or a conventional-commit `feat!:` header in a PR whose content is mechanical. Content is the grant, so the effect is bounded (skipped push workflows, a release-please bump the operator still merges). Fork PRs additionally cannot publish `deploy-shape`, so they fail the required-context check today. | `gh pr merge --squash` with no `--subject` | UNTESTED | consider `--subject` fixed from the verdict |
| Minor | SPECULATIVE | Parser divergence | The predicate compares PyYAML parses; PyYAML (YAML 1.1) and other consumers can read the same token differently (`010`). A change that is invisible to PyYAML but not to kubectl would need an existing such token in the file. No instance found. | n/a | UNTESTED | surface only |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness | B | Predicate and judge hold against every attack I could construct and discriminate correctly on live PRs; the only open paths need a tag collision. |
| Verification | C | 108 tests pass and most guards go RED, but the merging job's selection, sha source, triggers and permissions are unpinned (F1) and `verification.md` stops at PR 2. |
| Scope | A | Diff matches the proposal; prod, the receiver and #1741 untouched. |
| Reliability | B | Every error path fails to skip/unknown; closes are re-checked; concurrency group serialises runs. |
| Maintainability | B | Small pure functions; `classify_diff` is long but linear; no dead code. |
| Handoff-readiness | C | `verification.md` and `features.json` stale for PR 3; the `unstable` consequence is not written down. |

### Verdict

PASS WITH GAPS

No Blocker. F1 is a REAL Major (reproduced with `make mutate`), but it is a test-coverage gap in the "committed tests fail if the merging actor's condition widens" criterion, not a defect in current behaviour. By the severity x reality rule a REAL Major forces more than a bare PASS; I place the verdict at PASS-WITH-GAPS rather than FAIL because the switch is off, the pinned line and step gates are covered, and the fix is test-only and outside the contract set. If the owner reads AC4 strictly ("or the merge command changes" includes what feeds it), F1 is a FAIL until its tests land. Archive is not advisable yet: PR 4 and AC7 are outstanding.

### Recommended next steps

Outside the contract set (can be applied now without invalidating this review):
1. F1: add widening tests that pin the merge loop's selection and `read -r n sha`, and parse `on:` and `permissions:`; prove each with `make mutate`. Land before the flip.
2. F2: decide explicitly, on #1619, whether `Drift / staging` joins the judge's gate (recommended) or `unstable` is limited to a named allow-list; add the red-Drift negative test. Bind each overlay image to the bumped app's repo.
3. Align the `setup-python` pin in `deploy-merge.yml`; consider comparing `app.id` per context; test `base_ref` and the empty-PR close.
4. Write PR 3 evidence, the live `deploy-merge` output above and the promotion section into `verification.md`.

Contract set (`proposal.md`, `features.json`; editing them invalidates this review, so do it in the PR 4 round with a re-review): correct the AC7 note about `deploy-verify.yml`; add feature entries for AC4-AC6.
