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

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

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
