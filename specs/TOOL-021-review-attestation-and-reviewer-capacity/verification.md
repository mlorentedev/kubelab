---
tags: [spec, verification, templates]
created: "2026-08-19"
---

# Verification - TOOL-021-review-attestation-and-reviewer-capacity

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

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

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

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
