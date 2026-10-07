---
tags: [spec, verification]
created: "2026-10-07"
---

# Verification - APP-CONFIG-018-sale-digest-import

## Evidence

All tests are in `tests/test_n8n_shared_credentials.py` unless named, and run against a fake `kubectl` that records every payload piped into the pod, over the shipped prod plaintext config plus sentinel secrets.

- [x] AC1 -> `TestProdRun::test_credentials_land_before_the_workflow_that_uses_them`, `test_staging_imports_neither_the_digest_nor_smtp`, `test_the_cloudflare_credential_is_a_bearer_header`
- [x] AC2 -> `TestFailsClosed::test_a_missing_sale_value_fails_the_digest_naming_the_path[token|recipient|site_tag]`, `test_a_missing_smtp_value_fails_naming_the_path_and_no_workflow_uses_the_credential[host|port|user|pass]`, `TestProdRun::test_nothing_secret_reaches_the_output`, `test_the_secrets_travel_on_stdin_never_argv`; `tests/test_n8n_import.py::TestPlaceholderResolution::test_every_absent_path_is_named_at_once`
- [x] AC3 -> `TestFailsClosed::test_a_credential_nothing_imports_is_refused`, `test_a_shared_credential_referenced_under_the_wrong_id_is_refused`, `test_header_auth_nodes_that_disagree_on_the_id_are_refused`
- [x] AC4 -> `TestSmtpCredentialShape` (field names from n8n 2.12.3 `Smtp.credentials.ts`; `secure` for 465, 587, 25; payload built from `infra.smtp.*` with `secure: false` in the config and port 465 giving `true`)
- [x] AC5 -> `TestSharedLifecycle::test_removing_the_sale_leaves_the_shared_credential_in_place`, `test_two_workflows_using_it_import_it_once`, `test_a_workflow_needs_no_header_auth_credential_to_send_email`
- [x] AC6 -> `TestRegistries`, `TestSaleDigestWorkflow::test_every_placeholder_it_carries_is_mapped_to_a_path_with_an_owner`; `tests/test_secret_expiry.py` (every PROVIDER secret has a check), `tests/test_secrets_orphan_audit.py`
- [x] AC7 -> `TestReadme`

## Test status

- Mutation check of the new tests: 14 mutants of `toolkit/features/n8n_import.py` (secure always true, shared imported twice, shared in staging, SMTP missing-value check removed, reference check removed, resolver logs values, Header Auth disagree check removed, token check removed, shared gating removed, shared never imported, shared imported only when the sale is in the catalog, wrong From path, wrong password path), all killed. One survived on the first pass for the wrong reason (the held-back test failed on the workflow's own `smtp` key, not the credential) and was fixed.
- Whole unit suite (`pytest -m "not e2e and not infra and not integration"`): 3934 passed, 16 skipped, 2 xfailed, before the last two additions; the touched files re-run afterwards: 129 passed.
- `make lint`: clean. `mypy toolkit/`: no issues in 119 source files.
- Real-config smoke, no cluster: `toolkit infra n8n import --env prod --dry-run` renders `kubelab-smtp` from the real prod SOPS, and fails the digest closed naming both absent placeholder paths (the `sale_digest` block is not in SOPS yet). No `kubectl` was run.
- Not run: `make import-n8n ENV=prod` (the owner's step; the cluster is unreachable from here).

## Decisions made during implementation

- **Shared credentials are a second registry, not fields on `N8nImportSpec`.** A credential that belongs to no workflow cannot live on a spec without the next spec re-declaring it, and removing the sale would take it along.
- **`kubelab-smtp` is imported for the env whether or not a workflow uses it today**, so removing the last user never drops it. Prod only: staging has no email workflow, and widening it would make the automatic staging import in `deploy-k8s` depend on SMTP values.
- **`secure` follows the port**, not `infra.smtp.secure` (lesson-527).
- **Sender is `infra.smtp.user`**, the only From the Gmail relay keeps.
- **The recipient and site tag are SOPS values** under the sale's own block, with the token. The convention in `common.yaml` is plaintext for addresses (`infra.smtp.user`), but leaving-denver's runbook deliberately keeps these out of its public repository and this repository is public too. One block means one place to fill and one to delete.
- **The resolver stopped logging values** and reports every absent path at once.
- **Started over the WIP limit** (25 active specs, limit 10) with the reason recorded in `proposal.md`: the sale has a hard end date and none of the 25 is this change's to abandon.
- The workflow is `active: true` like its siblings: `publish:workflow` runs unconditionally, so the flag is cosmetic.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/toolkit-tooling/lesson-527-a-setting-that-shares-a-name-across-two-systems-does-not-share-its-meaning.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the registry extends TOOL-009's importer and ADR-036's shared SMTP without reversing either; the rationale is in this file and the README.
- [x] New pattern candidate for `00_meta/patterns/`? no: it does not yet recur in a second project.

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/APP-CONFIG-018-sale-digest-import/` -> `specs/archive/APP-CONFIG-018-sale-digest-import/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
