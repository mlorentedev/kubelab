---
tags: [spec, verification, templates]
created: "2026-06-20"
---

# Verification - CONSOLE-002-cross-context-bitacora

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 (Context round-trips git + Postgres projection) -> commit `<hash>` / test `TestContextRoundTrip`
- [ ] AC2 (append-only event history, prior events immutable) -> commit `<hash>` / test `TestAppendOnlyHistory`
- [ ] AC3 (GitHub adapter ingest + write verified by re-read) -> commit `<hash>` / test `TestGitHubAdapterVerifiedWrite`
- [ ] AC4 (default-deny per-context routing) -> commit `<hash>` / test `TestResolveContextPolicyDefaultDeny`

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

- [ ] Lesson for the repo's `docs/lessons.md`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/CONSOLE-002-cross-context-bitacora/` -> `specs/archive/CONSOLE-002-cross-context-bitacora/`
- [ ] Backlog entry in vault `11-tasks.md` ticked with PR link
- [ ] Promotions above executed (if any)
