---
tags: [spec, verification]
created: "2026-10-14"
---

# Verification - SEC-032-oidc-key-from-sops

## Evidence

- [x] AC1 -> commit `fbbfc072` / `tests/test_oidc_signing_key_single_store.py::TestTheDevStackReadsSops` (2 tests).
- [x] AC2 -> commit `fbbfc072` / `test_generating_a_key_writes_no_file` and the AC3 guard, which found `credentials.py` step 8 as a second writer.
- [x] AC3 -> commit `fbbfc072` / `test_nothing_reads_or_writes_a_host_copy`.
- [x] AC4 -> live on the Mac, 2026-10-14: no pem on the host; `authelia validate-config` rc 0 in the dev stack; the container's public key sha256 `9915cc14dfdff53a` equals the one derived from SOPS. Only exit codes and hashes were printed.
- [x] AC5 -> `docs/runbooks/sops-and-secrets.md`, `docs/runbooks/secrets-reference.md`, `docs/lessons/identity-secrets/lesson-568-a-reference-copy-of-a-secret-is-a-second-store.md`.

## Test status

- `poetry run pytest --no-cov -q tests/test_oidc_signing_key_single_store.py` with the related suites: 25 passed. 5/5 mutants red.
- `make validate-sync`: all generated files in sync.
- `make test-fast`: 4587 passed, 18 skipped, 2 xfailed, exit 0.

## Decisions made during implementation

- The key reaches the container as a Compose `secrets:` entry sourced from an environment variable, so no file exists on the host. Measured on Compose 5.6.0: the multi-line value arrives intact, mode 0444.
- `credentials generate` no longer touches the JWKS key at all. It minted a new key on every run and wrote it only to the pem, which is how the pems drifted from SOPS. Rotation stays `toolkit secrets jwks`.
- The dev Authelia crash loop seen while testing is pre-existing and unrelated (dev SOPS lacks a user password hash): SEC-034, #2247.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/identity-secrets/lesson-568-a-reference-copy-of-a-secret-is-a-second-store.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: SOPS as the single secret store is already the rule (CLAUDE.md, secrets runbooks); this removes an exception to it.
- [x] New pattern candidate for `00_meta/patterns/`? no: the single-store rule is already covered by the vault's secrets patterns; nothing here recurs in another project yet.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/SEC-032-oidc-key-from-sops/` -> `specs/archive/SEC-032-oidc-key-from-sops/`
