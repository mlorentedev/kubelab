---
tags: [spec, verification]
created: "2026-10-18"
---

# Verification - TOOL-001-secret-drift

## Integrated

Archived as **integrated** by this change, 2026-10-18 (kubelab#2443). It covers reporting and not gating: `secrets audit` names a missing catalogued key but exits 0, so it cannot gate a deploy. That half is #2499. Nothing was built under this spec, and
`toolkit secrets diff` does not exist. The need it named, a key added to staging and forgotten in
prod, is covered by a different design: `toolkit secrets audit` (`make secrets-audit`) checks each
environment against `SECRET_CATALOG`, the registry of which secret each env must have. That replaces
the pairwise compare. A catalogued key missing from prod is reported against prod whether or not
staging has it, and a key in no catalog entry fails the audit as an orphan.

Three criteria were never met. They are carried in kubelab#2499, not dropped.

## Evidence

Each acceptance criterion from `proposal.md`, mapped to where it now lives:

| AC | Status | Where |
|----|--------|-------|
| 1. Exits 0 when the envs agree | Integrated | `toolkit secrets audit`, which exits 0 on a clean report |
| 2. A staging-only key is listed and exits 1 | Partial | Listed under `Missing` for the env that lacks it (`_print_audit_result`). An uncatalogued key exits 1 as an orphan (`tests/test_orphan_secrets_ratchet.py`). A **catalogued** missing key exits 0, which is #2499. A cross-env diff for keys outside the catalog is #584 |
| 3. Never prints a value | Integrated | Key paths only. At the CLI boundary: `tests/test_secrets_value_shape.py::test_the_cli_fails_on_a_malformed_secret_and_names_only_the_key` asserts the value never reaches the output. In the walker: `tests/test_secrets_orphan_audit.py::TestItCannotLeakValues` (#1699) |
| 4. Decryption failure is a clear error with exit 2 | Not met | `_decrypt_sops` (`configuration.py:85-107`) logs and returns `{}`, so the audit reports every key missing and exits 0. That is established by reading the code: no test drives it, because the closest one patches `_decrypt_sops` away. #2499 adds the test with the fix |
| 5. `--format json` | Not met | #2499 |
| 6. A type-shape mismatch is flagged with exit 1 | Integrated, stronger | `SecretSpec.value_pattern` checks each value against its declared shape and fails the audit as `malformed` (#1699, lesson-413) |

## Test status

- No code changes under this spec. The tests named above are on master.
- No regressions: this archive changes only this spec folder and one CLAUDE.md line.

## Decisions made during implementation

- Archived as integrated rather than implemented as written. Catalog-driven audit (what each env
  must have) supersedes a pairwise compare (what two envs differ in): a key missing from both envs is
  invisible to the compare and caught by the catalog.
- TOOL-002 (#521, sync keys forward) named this spec as its report-only first step. That step is now
  `secrets audit`, and #521 stays open on its own.

## Review dispositions

Review `review.md` (nan/deepseek-v4-flash, **PASS**, reviewed `d1131364`). Six minor findings:

1. "Archived" in the past tense before the archive ran: applied, now "by this change".
2. #520 stays open after an archive, and nothing enforces closing it: no action needed. It is
   closed with the merge, per the checklist below. Gating that in `dotf` would be a tooling change
   outside this repo.
3. lesson-163 still sends readers to TOOL-001: applied, with a dated update note. The 2026-07-07
   process audit is a point-in-time snapshot and is left as written.
4. AC4 has no named test: applied. The row says it rests on reading the code, and #2499 adds the test.
5. AC3 under-cited: applied. The CLI-boundary test is named.
6. "Integrated" hides the gate gap: applied, now stated in the first paragraph.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? no: nothing was built; the design shift is recorded above and in #2499
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the catalog-driven audit predates this archive and is recorded where `SECRET_CATALOG` is documented
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: one project

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/TOOL-001-secret-drift/` -> `specs/archive/TOOL-001-secret-drift/`
- [ ] Tracking issue #520 closed as integrated, pointing at #2499 and #584
