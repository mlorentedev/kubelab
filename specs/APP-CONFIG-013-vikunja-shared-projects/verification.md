---
tags: [spec, verification, templates]
created: "2026-10-15"
---

# Verification - APP-CONFIG-013-vikunja-shared-projects

## Evidence

- [x] AC1 (token from SOPS, never argv/stdout, fails closed naming the key) -> `tests/test_sync_vikunja_cli.py` (6 tests); `make sync-vikunja ENV=staging` ran with nothing exported
- [x] AC2 (projects adopted, no `/namespaces`) -> `tests/test_vikunja_reconciler.py`, `tests/test_vikunja_api_contract.py`; staging run created 0 projects and adopted `Bitacora` (id 4)
- [x] AC3 (team, members, shares) -> `tests/test_vikunja_reconciler.py`; staging run: team `kubelab` created, `manu` added, 1 share at `write`
- [x] AC4 (`changed=0` on re-run) -> staging second run, 2026-10-16: `Vikunja is up to date (changed=0).` Prod pending
- [x] AC5 (requests checked against the server's swagger) -> `tests/test_vikunja_api_contract.py`, `tests/fixtures/vikunja/swagger-paths-1.0.0.json`, lesson-578
- [x] AC6 (declaration in `common.yaml`, invariants) -> `tests/test_vikunja_ssot.py`
- [ ] AC7 (Bitacora visible to `manu`): staging seen by the owner in the browser, 2026-10-16. Prod pending, so the string the feature greps for is deliberately absent until it is observed there
- [x] AC8 (no webhook; ticket) -> `test_the_reconciler_never_registers_a_webhook`; ticket #2326
- [ ] AC9 (honest expiry): parked, see decisions

## Test status

- `make test` on the part A branch: 5248 passed, exit 0 (2026-10-16)
- Staging manual smoke: first run created the team, added `manu`, shared the project and made 8 labels; the second run changed nothing
- Read-only token check, staging: `/projects`, `/teams`, `/labels` answer 200; `/tokens` and `/user` answer 401, `/info` 200

## Decisions made during implementation

- Both the human and the machine paths are one team: `kubelab`, right `write`, members `superadmin` and `operator`.
- The token has a single source, SOPS. A `--token` flag would put it in argv and an environment variable would let what ran differ from what the vault says.
- AC9 is parked. A Vikunja API token cannot ask Vikunja when it expires (`/tokens` answers 401 to it), so `PROVIDER` has no honest checker, `NEVER` is false (the token carries the expiry its minter chose) and `UNKNOWN` fails `test_every_catalog_entry_is_now_classified`. Options for the owner: (a) mint the token with the `tokens` group if Vikunja offers it and check through `/tokens`; (b) amend AC9 and extend the expiry model with a class for "expires, cannot be asked".

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/APP-CONFIG-013-vikunja-shared-projects/` -> `specs/archive/APP-CONFIG-013-vikunja-shared-projects/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
