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
