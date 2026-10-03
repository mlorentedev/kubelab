---
tags: [spec, verification]
created: "2026-06-14"
---

# Verification - WEB-010-interactive-cv

## Abandoned

Abandoned 2026-10-03 (DEBT-019, #2034): mlorente.dev is no longer built here. ADR-053 extracted the web app to its own repository and kubelab#611 is closed, so this spec has no code to change in kubelab. No task was started (0/21). Any interactive-CV work belongs in the web repository's own tracker.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 (`/v1/knowledge/chat` grounded+streamed) -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 (island live + correct answer) -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 (allowlist-only retrieval) -> commit `<hash>` / test `<name>`
- [ ] Criterion 4 (repositioned landing + email CTA) -> commit `<hash>` / test `<name>`
- [ ] Criterion 5 (GitHub/OSS proof surface live) -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

-
-

## Promotion candidates

- [x] Lesson for `kubelab/docs/lessons.md`? no: abandoned before implementation; the reason above is the only record needed
- [x] ADR-worthy decision for `kubelab/docs/adr/`? (ADR-045 already exists) no: abandoned before implementation; the reason above is the only record needed
- [x] New pattern candidate for `00_meta/patterns/`? Only if it recurs in >1 project. no: abandoned before implementation; the reason above is the only record needed

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/WEB-010-interactive-cv/` -> `specs/archive/WEB-010-interactive-cv/`
- [ ] Backlog entry / epic kubelab#611 ticked with PR link
- [ ] Promotions above executed (if any)
