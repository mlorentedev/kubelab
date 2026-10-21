---
tags: [spec, verification, templates]
created: "2026-09-03"
---

# Verification - DELIVERY-004-exempt-generated-deploy-prs

## Evidence

- AC1 (PR 1): `tests/test_deploy_shape.py` (38 tests). Live, 2026-10-21, `toolkit tools deploy-shape --pr N`:
  - #2581 exit 0 `mechanical`: web sha-f55a8c0 -> sha-9d79e52, head `5f8dec3e`
  - #2576 exit 0 `mechanical`: web sha-7ebd808 -> sha-f55a8c0, head `cfa843dd`
  - #2579 (human PR) exit 1 `not-mechanical`: file set
- AC2 (PR 1): `tests/test_review_attestation.py` (`test_the_staging_files_alone_no_longer_exempt`,
  `test_a_mechanical_verdict_at_the_head_sha_exempts`, `test_any_other_verdict_does_not_exempt`,
  `test_no_reviewer_is_named_in_the_module` extended to both modules).
- Mutation proofs (`make mutate`, each RED): `len(values) != 1` -> `< 1`; exact file set -> subset;
  attestation head-sha equality -> `True`; provenance compare -> `False`. The first one survived until
  `test_a_change_after_the_version_ends_it_too` was added.

## Test status

- `make test`: 6406 passed, 2 failed before fixes (pinned `gh pr view` field list, stale toolkit README); both fixed, targeted rerun green.

## Decisions made during implementation

- Operator 2026-10-21: attestation adopts the content predicate in PR 1; every registry app is in the class (api proven against this repository); names `deploy-shape`.
- Check-run, not commit status: only a check-run can answer `neutral` for a normal PR.
- Consumers recompute from master's code; the check is visible, not authoritative.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/DELIVERY-004-exempt-generated-deploy-prs/` -> `specs/archive/DELIVERY-004-exempt-generated-deploy-prs/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
