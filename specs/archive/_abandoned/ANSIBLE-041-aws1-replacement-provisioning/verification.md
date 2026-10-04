---
tags: [spec, verification, templates]
created: "2026-08-16"
---

# Verification - ANSIBLE-041-aws1-replacement-provisioning

## Abandoned

Abandoned 2026-10-03 (DEBT-019, #2034): the host is gone. aws1 was destroyed on 2026-08-23 (GCP-001 AC6), and the hub is gcp1 (ADR-063). The live hub's replace path does what this spec asked for: `make gcp1-replace` runs `provision NODE=gcp1`, so `node_maintenance` is reinstalled on every recreate. No task was started (0/21). `make aws1-replace` still carries the gap for the dormant `networking.aws` rebuild recipe; that stays on kubelab#1102 for the operator to keep or close.

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

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons.md`? no: abandoned before implementation; the reason above is the only record needed
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: abandoned before implementation; the reason above is the only record needed
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: abandoned before implementation; the reason above is the only record needed

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/ANSIBLE-041-aws1-replacement-provisioning/` -> `specs/archive/ANSIBLE-041-aws1-replacement-provisioning/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
