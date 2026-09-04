---
tags: [spec, tasks, templates]
created: "2026-09-04"
---

# Tasks - DELIVERY-004-exempt-generated-deploy-prs

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feat/1619-exempt-generated-deploy-prs` ✓ 2026-09-04
      (leads with the bitácora issue number per `pattern-git-workflow` §3, not the spec id)
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-09-04
- [ ] No open questions left in `proposal.md` "Risks / open questions"
      **BLOCKED** — the auto-merge item is marked MUST-RESOLVE and belongs to the operator.
      It gates PR2 only; PR1 proceeds.

## Implementation

> Two PRs. **PR1 (AC1–AC4) is self-contained and lands regardless of the operator's
> auto-merge decision.** PR2 (AC5) is gated on it. Sequenced this way deliberately:
> the reviewer-capacity finding is the larger share of the measured damage and must
> not be held hostage to a policy question.

### PR1 — the diff carries nothing reviewable

- [ ] [P] [AC1] Failing test: a PR whose changed-file set is exactly the staging deploy pair
      classifies as `exempt`. Asserts against `classify()` with a fixture built from the six
      measured PRs. Red today — no such signature is declared.
- [ ] [AC1] Declare `staging deploy (single app)` and `prod promote (single app)` in
      `harness/review-attestation.json` under `exempt.signatures`, each with a `why` naming the
      PRs it was measured on (#1560, #1582, #1590, #1601, #1617 staging; #1618 prod), matching
      the standard the three `release-please` entries already set.
- [ ] [AC3] Failing test **first**, then keep it: a PR carrying a signature's files **plus one
      unrelated file** does NOT classify as `exempt`. This is the guard that decides whether
      the whole feature is an exemption or a bypass — write it before trusting set equality.
- [ ] [AC3] Prove it goes red: widen the comparison to a subset check (`changed <= set(...)`),
      confirm the negative test fails, restore. **Commit before mutating** — `git checkout HEAD --`
      is only safe against a committed state.
- [ ] [AC1] Extend the existing test that forbids reviewer identities in
      `toolkit/features/review_attestation.py` to also forbid signature paths. **Extend, do not
      fork** — one test owning "the module names no policy data" beats two that drift apart.
- [ ] [P] [AC4] Suppress the paid reviewers on a matching diff. The only genuinely new code, and
      the half whose failure is silent: express it as the SAME changed-file predicate, evaluated
      from the same file set. Never a branch-prefix or author condition (`RELEASE_PLEASE_TOKEN`
      is a PAT and any branch can be named to match).
- [ ] [AC4] Static test: no workflow condition added by this spec references a branch prefix or
      an author. Cheap, and it is the assertion that keeps the predicate honest after a future edit.
- [ ] [AC2] [AC4] Live verification on the next real deploy PR and the next real promote PR:
      `review-attestation` status reads `exempt` naming the matched signature, and CodeRabbit and
      Codex checks are absent. Record the PR numbers and the status strings in `verification.md`.
      **Evidence from a live PR, not from a unit test** — the unit test proves `classify()`, the
      status proves the gate reached the same conclusion on a real payload.

### PR2 — no human needs to decide (staging only)

> **Gated on the operator's decision.** Do not start until the Risks item is resolved.

- [ ] [AC5] Enable auto-merge scoped to the staging signature only. Prod keeps its human merge —
      the promotion decision is the human's contribution there, not the diff inspection.
- [ ] [AC5] Assert prod is untouched: a promote PR observed after landing still requires a merge.
      Without this the scope is claimed rather than demonstrated.
- [ ] [AC5] Measure latency over the first five real staging deploy PRs after landing. Report
      the number against the 11h (#1560) / 19h30m (#1590) baseline. A number, not "faster".

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder
- [ ] `#1203` updated: contention reduced, displacement NOT fixed — so nobody reads this as closing it

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Note on AC2, AC4 and AC5: their verification is an observation of a live pull request, which no
single shell command can conjure on demand. Their `verification` fields read the recorded PR
number back out of `verification.md` and re-query it, so the command stays executable and the
evidence stays falsifiable — rather than being declared unverifiable and quietly skipped.
