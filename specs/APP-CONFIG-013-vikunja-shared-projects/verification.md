---
tags: [spec, verification, templates]
created: "2026-10-15"
---

# Verification - APP-CONFIG-013-vikunja-shared-projects

## Evidence

Disposition 2026-10-22: archived as superseded by CONSOLE-005 (#2587), which retires Vikunja (ADR-066 amendment, #2575 merged `32247509`). AC7 and AC9 are Not met for that reason and are not claimed as passing.

| AC | Status | Proof |
|----|--------|-------|
| AC1, token from SOPS, never argv/stdout, fails closed naming the key | Met | `tests/test_sync_vikunja_cli.py` (6 passed, 2026-10-22); #2331 (`87f548b6`); `make sync-vikunja` ran with nothing exported on staging (2026-10-16) and prod (2026-10-18) |
| AC2, projects adopted, no `/namespaces` | Met | `tests/test_vikunja_reconciler.py`, `tests/test_vikunja_api_contract.py` (47 passed with the client tests, 2026-10-22); #2324 (`9eafa564`). Prod, 2026-10-18: `Bitacora` (project 2) adopted, none created (issue #1701, comment 6243987329) |
| AC3, team, members, shares | Met | `tests/test_vikunja_reconciler.py -k 'team or share or idempotent'` (3 passed, 2026-10-22). Prod, 2026-10-18: 1 team, 1 member, 1 share; staging, 2026-10-16: team `kubelab`, `manu` added, 1 share at `write` |
| AC4, `changed=0` on re-run | Met | Staging 2026-10-16 and prod 2026-10-18, second run `changed=0` (issue #1701 comments) |
| AC5, requests checked against the server's swagger | Met | `tests/test_vikunja_api_contract.py`, `tests/fixtures/vikunja/swagger-paths-1.0.0.json`, lesson-578 |
| AC6, declaration in `common.yaml`, invariants | Met | `tests/test_vikunja_ssot.py` (4 passed, 2026-10-22) |
| AC7, `Bitacora` visible to `manu` in prod | Not met, superseded | Seen by the owner in the browser on staging, 2026-10-16. Never observed on prod: the service is retired by CONSOLE-005 #2587 |
| AC8, no webhook; ticket | Met | `test_the_reconciler_never_registers_a_webhook` (1 passed, 2026-10-22); ticket #2326 (APP-CONFIG-019) |
| AC9, honest expiry | Not met, superseded | Code half landed in #2464 (`99c65d6b`): `SecretSpec` `kind=EXTERNAL` for staging/prod and `Expiry.DECLARED`, 15 tests in `tests/test_vikunja_reconciler_token_spec.py`. No declared expiry date is recorded per env in `values/<env>.yaml`. The class stays open because the service is retired by CONSOLE-005 #2587 |

## Test status

- `make test` on the part A branch: 5248 passed, exit 0 (2026-10-16)
- Staging manual smoke: first run created the team, added `manu`, shared the project and made 8 labels; the second run changed nothing
- Read-only token check, staging: `/projects`, `/teams`, `/labels` answer 200; `/tokens` and `/user` answer 401, `/info` 200

## Decisions made during implementation

- Both the human and the machine paths are one team: `kubelab`, right `write`, members `superadmin` and `operator`.
- The token has a single source, SOPS. A `--token` flag would put it in argv and an environment variable would let what ran differ from what the vault says.
- AC9 was parked, then implemented as `Expiry.DECLARED` in #2464 (the option (b) below); the per-env dates were never recorded, and the spec is archived instead (see Evidence). A Vikunja API token cannot ask Vikunja when it expires (`/tokens` answers 401 to it), so `PROVIDER` has no honest checker, `NEVER` is false (the token carries the expiry its minter chose) and `UNKNOWN` fails `test_every_catalog_entry_is_now_classified`. Options for the owner: (a) mint the token with the `tokens` group if Vikunja offers it and check through `/tokens`; (b) amend AC9 and extend the expiry model with a class for "expires, cannot be asked".

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/process-method/lesson-578-a-client-test-checks-its-requests-against-the-servers-own-swagger-not-a-fake.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? yes: docs/adr/adr-066-self-hosted-task-platform.md (the 2026-10-20 amendment, #2575, records the retirement that supersedes this spec)
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: the swagger-fixture check is recorded in lesson-578 and the service it protects is being retired; one project

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/APP-CONFIG-013-vikunja-shared-projects/` -> `specs/archive/APP-CONFIG-013-vikunja-shared-projects/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
