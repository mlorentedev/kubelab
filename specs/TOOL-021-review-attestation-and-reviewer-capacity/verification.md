---
tags: [spec, verification, templates]
created: "2026-08-19"
---

# Verification - TOOL-021-review-attestation-and-reviewer-capacity

## Evidence

Mapped 2026-10-10 against master `41f21b99`, for DEBT-019 (#2034) and #2171. Every row is a real PR or a named test.

| AC | Status | Evidence |
|---|---|---|
| AC1: a notice-only PR is red, on a real PR | met | #1166 (2026-08-19): CodeRabbit and Codex both posted quota notices and the status read `failure — not reviewed, and not declared as such` ("Live behaviour" below). |
| AC2: a reviewed PR is green, a PR with no output is red | met | #1165 flipped from `declined` to `attested` when CodeRabbit filed a review. The Phase 0 backtest counts 3 `pending` PRs, the no-output state, and `pending` exits 1. |
| AC3: content, not login, decides | met | See "AC3" below: CodeRabbit's own comments, same login, give opposite verdicts. Test: `test_the_same_account_is_declined_or_attested_by_what_it_wrote`. |
| AC4: a PR-Agent comment review attests from GraphQL or REST | met, amended | See "AC4" below. Tests: `test_login_spelling_does_not_change_the_verdict`, `test_the_gate_reads_its_payload_from_gh_pr_view_only`. |
| AC5: a reviewer change is a config edit | met | #1192 (`c143da97`) changed CodeRabbit's markers and touched only `harness/review-attestation.json` and its test. `test_no_reviewer_is_named_in_the_module` keeps it that way. |
| AC6: PR-Agent posts inline comments with `NAN_API_KEY` alone | AC6-PENDING | See "AC6" below. |
| AC7: credential material never reaches the endpoint | met | #2094 (2026-10-07) changed only `infra/config/secrets/prod.enc.yaml`. Run 37589208861 skipped the PR-Agent step and ran "Declare unreviewed — diff is entirely excluded". Test: `test_credential_material_is_excluded_from_the_model_call`. |
| AC8: a release PR is neither reviewed nor left pending | met | #1680 (2026-09-05): the status read `exempt from review` at 21:05:54Z, and the PR-Agent run on its head was `skipped`. CodeRabbit reviewed it later, so it ended `attested`; attestation outranks exemption by design. |
| AC9: the reviewer's own failure is red | met | See "AC9" below: #2178 (unreachable endpoint) and #2183 (invalid credential). |
| AC10: the gate is required, so an unreviewed PR is BLOCKED | met | See "AC10" below: #2178, with every other required check green. |
| AC11: nothing enables auto-merge, by test | met | #2152 (`5b520047`). |

### AC3 — one account, opposite verdicts

Fixture `tests/fixtures/review_attestation/coderabbitai-same-account.json` is cut from CodeRabbit's real comments. #2057 holds a rate-limit notice only. #2098 holds one persistent comment with the same notice, which CodeRabbit later edited to carry its review. Each payload has the same login and `authorAssociation`. The first classifies `declined` and the second `attested`. The test was red against its mutant. The fixture's `orgId` and `scope` URL parameters are redacted, because the original carried a token-shaped value.

Replayed across 80 merged PRs, classifying on CodeRabbit's output alone: 40 declined, 28 attested, 8 disclosed, 2 pending, 2 exempt. One login, and the verdict follows what it wrote.

### AC4 — amended: the gate reads GraphQL only

The criterion asks for the verdict to hold "whether the payload came from GraphQL or REST". The gate never receives a REST payload. Its only input is `gh pr view --json ... comments,reviews ...`, which is GraphQL, and a test now pins that (`test_the_gate_reads_its_payload_from_gh_pr_view_only`, red against its mutant). The REST spelling still reaches the classifier through fixtures and through the publish check in `pr-agent.yml`, which reads REST and matches `github-actions[bot]`. Login folding makes both spellings one reviewer (`test_login_spelling_does_not_change_the_verdict`). So the criterion is amended to: the verdict does not depend on the API's login spelling, and the gate's payload source is pinned.

### AC6 — inline comments

AC6-PENDING

`fallback_models` is no longer `[]`. #1202 (`f0fffef3`, ticket #1203) added `openai/deepseek-v4-flash` as the single fallback. It calls the same NaN endpoint with the same `NAN_API_KEY`, so the sole-credential half of AC6 holds.

### AC9 — the reviewer's own failure, injected

#2178 was a throwaway PR (closed unmerged, branch deleted) that broke the reviewer in two pushes.

1. **Unreachable endpoint**, `130264f8`. `OPENAI__API_BASE` pointed at `api.nan.builders.invalid`. RFC 6761 reserves `.invalid`, so the name never resolves, and the host keeps the substring the streaming test reads. Run 38043052626:
   - both models were tried, and each returned `litellm.InternalServerError: ... Connection error.`;
   - PR-Agent logged `Failed to review PR: Failed to generate prediction with any model of ['openai/mimo-v2.6-flash', 'openai/deepseek-v4-flash']`, then `Tool reported success but recorded a failure; failing the action`;
   - steps `PR-Agent` and `Fail if no review was published` both concluded `failure`;
   - `review-attestation` read `failure — not reviewed, and not declared as such`.
2. **Invalid credential**, on #2183 at `b0b1c7d6`, a second throwaway (closed unmerged, branch deleted). #2178's own run for this push was evicted from the shared review queue (#2179), and a `/review` re-run reviews with master's workflow and key, so it proves nothing about the PR's (lesson-552). #2183 set only `OPENAI__KEY` to a placeholder and was reviewed by its `pull_request` run, 38045178907:
   - both models were tried, and each returned `litellm.AuthenticationError: AuthenticationError: OpenAIException - Invalid API key.`;
   - PR-Agent logged `Failed to review PR: Failed to generate prediction with any model of ['openai/mimo-v2.6-flash', 'openai/deepseek-v4-flash']`, then `Tool reported success but recorded a failure; failing the action`;
   - steps `PR-Agent` and `Fail if no review was published` both concluded `failure`;
   - `review-attestation` read `failure — not reviewed, and not declared as such` at 10:52:55Z, while `Validate`, `Detect Changes` and `Tests` passed, and the PR was `MERGEABLE` and `BLOCKED`.

The authentication error is what tells this half from the first: the endpoint answered and refused the key.

### AC10 — BLOCKED, isolated to the attestation

Branch protection on `master`, read live 2026-10-10:
- required contexts: `Validate`, `Detect Changes`, `review-attestation`, `Tests`, not strict;
- `required_pull_request_reviews` is present with `required_approving_review_count: 0`, so no approval rule can block a merge;
- `enforce_admins: true`.

#2178 at `130264f8`, 10:07:23Z: `Validate`, `Detect Changes` and `Tests` passed and `review-attestation` failed. `mergeable: MERGEABLE`, `mergeStateStatus: BLOCKED`. The attestation is the only required check that is not green, so it alone blocks the merge.

The contrast is #2177 at `5618e9d2`: the same four required contexts all passed, `review-attestation` read `success`, and it merged as `f1c952a8` at 10:34:59Z. Of the required checks, only the attestation differs between the two PRs.

## Phase 0 — backtest, before the gate governs anything

Real payloads replayed through `classify()`. A monitor that has never seen history is a hypothesis.

**Last 40 merged PRs:**

| verdict | count |
|---|---|
| declined | **32** |
| attested | 5 |
| pending | 3 |

**35 of the last 40 merged PRs were not reviewed** — 32 carried a reviewer's own notice that it could not review, and merged anyway. The eleven counted in `proposal.md` came from the days someone happened to look; this is the rate. All five attestations are the same reviewer, on the occasions its quota allowed.

**Every release PR in history (16), against the exempt signatures:**

| verdict | count | reading |
|---|---|---|
| exempt | 9 | the three declared shapes, each exercised by real history |
| attested | 1 | #122 was genuinely reviewed — attestation outranks exemption, as designed |
| declined / pending | 6 | two shapes deliberately left undeclared |

The six refusals are correct rather than gaps: five are `apps/web/*` releases and web moved to its own repo (ADR-053), so the shape is dead; one is a two-file `edge/errors` release predating `version.txt`. Declaring signatures for shapes that can no longer occur would widen the exemption in exchange for nothing.

**The backtest corrected the registry.** The `errors only` signature carried a comment calling it unobserved and declared "by construction" — written from a four-PR sample. History shows it four times. Wrong in the safe direction, but wrong, and a reader would have taken it as grounds to delete the entry.

## Live behaviour, 2026-08-19 — both directions, on real PRs

Not fixtures. The gate went live with #1162 and was exercised the same hour by two unrelated PRs.

**#1165 — the flip.** Opened, and the attestation status went **red**: Codex had posted its quota notice, which is a notice that no review ran, and CodeRabbit had not spoken. CodeRabbit then filed a real review with six findings; `pull_request_review: [submitted]` fired, the job re-ran, and the status became:

    review-attestation: success — a review happened

That is AC2's positive half and the re-evaluation path, demonstrated end to end without anyone touching the gate. It also confirms a design assumption rather than leaving it inferred: this reviewer files through the **reviews API**, which is why its registry entry carries an empty `review_markers` — the backtest predicted it and production agreed.

**#1166 — the refusal.** Both reviewers declined on the same PR, minutes apart:

    coderabbitai:              "Review limit reached … next review available in 52 minutes"
    chatgpt-codex-connector:   "You have reached your Codex usage limits for code reviews"
    review-attestation: failure — not reviewed, and not declared as such

Two independent account-wide quotas exhausted simultaneously, which is the correlation this spec was written about. Before the gate, that PR would have shown `CodeRabbit  pass`. AC1, with production data.

**The escape has deliberately not been used yet.** #1166 is genuinely unreviewed, so it is genuinely red; declaring it would be the first use of `merged-unreviewed`, and that path should first be exercised on a merge that truly proceeds without review rather than on one that is simply waiting for a quota to reset.

## The fail-open, caught in the act — #1165, 2026-08-19

The clearest evidence this spec will get, and nobody staged it. On one commit, at the same moment:

    CodeRabbit:          success  — "Review rate limited"
    review-attestation:  success  — "a review happened"

A fix commit was pushed for CodeRabbit's six findings. On the new head SHA CodeRabbit had no quota left, so it published **`success`** with a description saying it had not reviewed — the exact failure #1140 was filed about, in production, while being watched. The gate was not fooled: it read the earlier substantive review through `reviews[]` and published `attested` at 03:22:53, nineteen seconds after CodeRabbit's 03:22:34. **Content over check status**, on the input it was built for.

Before that, on the previous SHA, the full flip: `declined` (Codex quota notice, nothing else) -> CodeRabbit files a real review -> `pull_request_review: submitted` -> `attested`. The re-evaluation path end to end, unassisted.

## A cancelled run is not a failed one — and it is an AC10 landmine

`gh pr checks` on the same PR shows two rows with opposite verdicts:

    attestation          fail    <- the JOB
    review-attestation   pass    <- the STATUS

The `fail` is a rendering artefact: the API reports `status=completed, conclusion=cancelled`. `concurrency: cancel-in-progress: true` did it — a push started one run, CodeRabbit's status update started a second, and the first was killed mid-flight. That is the design working, and it is why the product is a **commit status** rather than a check-run: a status is revisable, a check-run belongs to the run that created it.

**The consequence for AC10 is a trap worth naming before anyone hits it.** Promoting the wrong name to required inverts the gate:

- Required must be the **commit status `review-attestation`**.
- Required must **not** be the check-run **`attestation`** — a cancelled-by-design run would block the merge permanently, and cancellation is now the common case, because a reviewer speaking is itself a trigger.

A proposed mitigation was considered and rejected: a final step guarded by `if: cancelled()` exiting 0. It cannot work — a cancelled job's conclusion is `cancelled` no matter what its steps do, so the step would run and change nothing. The correct mitigation is naming the right context in branch protection, which AC10 now says explicitly.

## Test status

- `make test` on the archive branch: TEST-STATUS-PENDING
- `tests/test_review_attestation.py`: 43 passed. The two tests added for AC3 and AC4 were each red against their mutant.
- Live: the gate has judged every PR since #1162 (2026-08-18). The demonstrations above are on real PRs.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **Part 1 in the toolkit, not as a shell script.** Upstream is 396 lines of bash. This repo's other gate lives in `toolkit/features/` with its tests beside it, for a stated reason — the negative case then runs on every commit instead of needing a live PR. Porting the shell would have introduced a second pattern for the same job.
- **Each release shape declared, rather than relaxing the match.** Exemption is exact set equality in both directions and release tooling opens per-app releases, so one superset signature exempts three observed PRs and refuses a fourth. Loosening to a subset would have exempted a PR touching only the manifest; enumerating shapes keeps the strictness, and an undeclared shape fails red.
- **`model_weak` dropped, not ported.** `auto_describe` is off so it has nothing to do, and the model upstream names is one this repo's reviewer pool rejects on quality grounds.
- **The inert upstream setting was replaced, not reimplemented.** `ignore_pr_source_branches` is loaded and never consulted on the Action path; the job-level `if:` is the same intent at the layer that runs. A test asserts the setting is not re-added, so the `if:` does not later read as redundant.
- **Public-repo hardening with no upstream counterpart.** The slash-command path is restricted by author association. **A first draft said upstream "did not need it — its repo is private". That was wrong: measured 2026-08-19, upstream is public too.** The unrestricted condition was a live exposure there, not a difference in context, and reporting it produced a fix on their side. The correction matters more than the fix: I inferred a condition's safety from a repository property I never checked, inside a port whose whole discipline is measuring rather than assuming.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-021-review-attestation-and-reviewer-capacity/` -> `specs/archive/TOOL-021-review-attestation-and-reviewer-capacity/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
