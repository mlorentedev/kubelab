---
tags: [spec, verification]
---

# Verification - TOOL-009-n8n-workflow-import

> Filled during implementation (rides the notify branch post TOOL-008 merge).

## Evidence

- [ ] Criterion: `make import-n8n ENV=staging` → workflow active, no UI → smoke output
- [ ] Criterion: idempotent re-run → no duplicates → second-run output
- [ ] Criterion: secret never on persistent disk/argv → code review + `/dev/shm` usage
- [ ] Criterion: delete workflow + re-import → identical → smoke output
- [ ] Criterion: credential-render unit test → test name + result

## Test status

- Unit tests: `<command>` → `<output>`
- Live smoke (staging): `<command>` → `<observed>`
- No regressions: `make test` → `<output>`

## Decisions made during implementation

-

## Promotion candidates

- [ ] Lesson for `docs/lessons.md`? <yes/no>
- [ ] ADR-worthy? <yes/no — likely folds into ADR-044 / APP-CONFIG-003>
- [ ] Pattern for `00_meta/patterns/`? <yes/no — "service config as code via CLI import from SOPS">

## Archive checklist

- [ ] `proposal.md` → `status: archived`
- [ ] Folder → `specs/archive/TOOL-009-n8n-workflow-import/`
- [ ] Issue #108 ticked with PR link
- [ ] README manual-import section removed
