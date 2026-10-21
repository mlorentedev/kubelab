---
tags: [spec, verification, templates]
created: "2026-08-27"
---

# Verification - GITOPS-003

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 -> PR1, blocked on the PAT (Risk 2)
- [ ] AC2 -> PR2
- [ ] AC3 -> PR3, after web#435 serves `commit` on staging
- [x] AC4 -> PR4 (`feat/gitops-003-verify-staging`): `tests/test_product_verify.py` (34 tests); live runs below
- [x] AC5 -> #1276, `tests/test_argocd_notification_triggers.py`
- [ ] AC6 -> PR5
- [ ] AC7 -> PR2

## Test status

- `poetry run pytest tests/test_product_verify.py -q --no-cov` → `34 passed`
- Mutation (`make mutate`): dropping `sync.revision == head` from the ready condition → 3 failed; treating a missing `commit` as present (`if False:`) → red. Both restored.
- Live, 2026-10-20, master `ed5747f`, from the workstation on the mesh:
  - `make verify-product APP=web ENV=staging TIMEOUT=45` → exit 3: `sync=Synced at ed5747f (HEAD ed5747f); last operation Succeeded at 4ab3083`, `serves no commit (version '1.16.0'), expected '7ebd808'`. Correct today: web#435 has not shipped.
  - `make verify-product APP=web ENV=prod TIMEOUT=45` → exit 0: `serves version '1.16.0', expected '1.16.0'`.
  - `make verify-product APP=api ENV=staging` → exit 2: `'api' has no product contract at ed5747f`.

## Decisions made during implementation

- Product-agnostic, decided with the operator 2026-10-20: host and image from the contract snapshot, `/version.json` a platform convention; no contract schema change (IDP-042 untouched).
- "Synced at HEAD" is `sync.revision`, not the last operation's revision; Application health is not a condition (lesson-608).
- `commit` compared by strict equality with the tag minus `sha-`; a prefix match would accept a truncated answer.
- A missing `commit` keeps waiting until the deadline (an old pod may answer during a rollout), then exits 3.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes: lesson-608 (Synced at HEAD is `sync.revision`); lesson-407 already holds the incident
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/GITOPS-003/` -> `specs/archive/GITOPS-003/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
