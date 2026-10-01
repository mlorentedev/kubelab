---
tags: [spec, verification]
created: "2026-10-01"
---

# Verification - BACKUP-068-app-restore-drill

## Evidence

- [x] AC1 -> `test_a_rotated_opaque_identifier_fails_and_never_starts_a_server`, `test_authelia_reads_the_encryption_check_text_because_it_exits_0_on_failure`, `test_authelia_checks_the_key_before_starting_the_server`, `test_a_server_that_never_answers_healthy_fails[authelia]`, `test_an_answer_that_is_not_healthy_is_not_a_pass[authelia]`, the `compare` tests; prod runs below.
- [x] AC2 -> `test_a_workflow_missing_from_the_restore_fails_and_is_named`, `test_a_workflow_created_after_the_snapshot_does_not_fail`, `test_n8n_names_a_key_that_is_not_the_datas`, `test_n8n_fails_when_a_credential_does_not_decrypt`, `test_an_n8n_that_exited_is_not_waited_on`, `test_live_or_the_repository_that_cannot_be_read_is_cannot_check` (5 cases), `test_a_live_database_with_no_durable_rows_is_cannot_check`.
- [x] AC3 -> `test_the_key_travels_only_as_a_private_file_into_a_container_with_no_network` (both), `test_live_is_read_from_the_file_never_by_running_the_app_in_its_pod` (both), `test_a_container_that_fails_to_start_is_still_removed`, `test_a_complete_restore_that_leaves_its_container_behind_fails`, `test_a_complete_restore_that_leaves_the_data_on_disk_fails`; `_torn_down` asserted on the failing paths.
- [x] AC4 -> the two prod runs below; `test_the_drill_reads_the_files_keys_and_target_the_ssot_declares`.
- [x] AC5 -> `docs/runbooks/offsite-backup-restore.md` "### Authelia and n8n" (drill and real restore). Taking a prod app offline under `selfHeal` has no safe path yet; the runbook says so and points at #1998.

### Prod run, 2026-10-01, from the workstation

```text
authelia + n8n restore drill — newest capture in R2 into scratch containers (prod)
[INFO] drill: authelia: snapshot a59acffe taken 2026-10-01T16:00:09.481525257Z
[INFO] drill: authelia: user_opaque_identifier: 4 live, 4 restored
[INFO] drill: authelia: user_preferences: 1 live, 1 restored
[INFO] drill: authelia: totp_configurations: 0 live, 0 restored
[INFO] drill: authelia: webauthn_credentials: 0 live, 0 restored
[INFO] drill: authelia: schema version live 23, restored 23
[SUCCESS] drill: authelia: the SOPS storage key opens the restored database
[SUCCESS] drill: authelia: the server starts on the restore and answers healthy
[INFO] drill: authelia: RTO 3s from download to a server that answers
[SUCCESS] drill: snapshot a59acffe restores authelia completely
[INFO] drill: n8n: snapshot a59acffe taken 2026-10-01T16:00:09.481525257Z
[INFO] drill: n8n: workflow_entity: 4 live, 4 restored
[INFO] drill: n8n: credentials_entity: 2 live, 2 restored
[SUCCESS] drill: n8n: the server starts on the restore with the SOPS key
[SUCCESS] drill: n8n: every restored credential decrypts
[INFO] drill: n8n: RTO 18s from download to a server that answers
[SUCCESS] drill: snapshot a59acffe restores n8n completely
rc=0
```

Afterwards: no `*drill-*` container in `docker ps -a`, no `*drill-*` directory under the temp dir (`/tmp`).

### Prod run with a random key in place of each SOPS key

`drill_apps(env="prod")` with `ConfigurationManager.get_secret_by_path` answering a random 32-byte hex for both key paths and the real value for everything else:

```text
[ERROR] FAIL authelia: the SOPS storage key does not open the restored database
[ERROR] FAIL n8n: the SOPS key is not the key this data was encrypted with
RESULT False
```

No container left. The same snapshot passes with the real keys, so the key is the only variable.

### Mutation check

Each guard was broken in turn on a committed tree, `tests/test_app_drill.py` run with `-x`, and the file restored with `git checkout HEAD --`.

| Mutation | Result |
|---|---|
| encryption check text ignored | killed |
| teardown result ignored (container) | killed |
| teardown result ignored (directory) | killed |
| identity digest not compared | killed |
| live with no durable rows accepted | killed |
| newer-by-id rule removed | killed |
| newer-by-timestamp rule removed | killed |
| `--network none` → `bridge` | killed |
| key file created `0644` | killed |
| credential decryption result ignored | killed |
| "Mismatching encryption keys" not detected | killed |
| health answer not read, exit code only | killed (after adding `test_an_answer_that_is_not_healthy_is_not_a_pass`) |
| PV path count not checked | killed |
| `integrity_check` skipped | killed |
| incomplete restore still started | killed |
| empty image accepted | killed (after adding the `image_out=""` case) |
| exited container waited on until the deadline | killed (after adding `test_an_n8n_that_exited_is_not_waited_on`) |

## Test status

- `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_app_drill.py` → 41 passed on `416ab991` (master, 2026-10-01). It read 39 when first recorded, before the squash added two tests.
- `make test` on `416ab991`: 3399 passed, 16 skipped, 154 deselected, 2 xfailed, rc 0.

## Decisions made during implementation

- **Live is read from the files, not the app.** The spike used `kubectl exec ... n8n list:workflow`; in the live pod that answers nothing at `N8N_LOG_LEVEL=warn` and starts a second n8n under a 512Mi limit at 365Mi (lesson-500, OPS-033). Reading the database over SSH the way the capture does also lets the same SQL run on both sides, which turned "schema version and workflow ids" into row-level completeness for both services.
- **Durable tables only.** Sessions, tokens, logs and bans turn over inside the snapshot interval, so comparing them would fail healthy restores. The opaque identifiers are compared by content too, as a digest: a changed `sub` is a new identity to every OIDC client.
- **Newer rows without a timestamp** are recognised by an `AUTOINCREMENT` id above the restore's highest. An empty restore never excuses a missing row.
- **The image comes from the live Deployment**, as in the Postgres drill, so the drill tests the image that would have to open the data.
- **Authelia's key is checked by the CLI before the server starts** (container idles on `sleep`, then `docker exec -d authelia`), so a wrong key reads as "the key does not open it", not as "the server did not start".
- **What prod measured, and what only the tests did.** With a wrong n8n key, prod failed at start-up ("Mismatching encryption keys", because the capture carries `config`). The decrypt step after it, `export:credentials --decrypted` exiting non-zero on data the key cannot open, is covered by `test_n8n_fails_when_a_credential_does_not_decrypt` and was not observed on real data: in a real capture the start-up guard always fires first.
- **One throwaway Authelia user**: the file backend refuses an empty user list (measured: `users: non zero value required`). Its argon2 hash is generated at drill time from a random password and never written to the repo.

## Review dispositions

Pooled adversarial review (`nan/deepseek-v4-flash`, 2026-10-01, `review.md`): **PASS-WITH-GAPS** on `416ab991`. It found no code defect: the guards are real, and the secrets discipline holds. There are five Minor findings.

- **Promotion lines the archive pre-flight cannot parse** (REAL). Applied: every line now asks a question and answers `yes: <path>` or `no: <reason>`.
- **Test evidence not reproducible as recorded** (REAL). Applied: `test_app_drill.py` re-run on `416ab991` → 41 passed. The `make test` line pinned to the pre-squash `33e2859f` is replaced by a run on `416ab991`.
- **A lost trailing row with no timestamp reads as newer than the snapshot** (THEORETICAL). Ticketed, #2015 item 1. The fix touches `compare()` and the spec's contract, which would stale this review.
- **Two parses raise instead of CANNOT CHECK** (THEORETICAL). Ticketed, #2015 item 2.
- **`run_drill` and `_prove_authelia` over the complexity bar** (REAL, shared by all four drills). Ticketed, #2015 item 3, as one extraction for the drill family rather than a BACKUP-068-only refactor.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/storage-backup/lesson-500-n8n-cli-answers-nothing-at-log-level-warn.md
- [x] ADR-worthy decision? no: the drill pattern of BACKUP-046/040/067 applied to two more sources.
- [x] New pattern candidate for `00_meta/patterns/`? no: single project.
- [x] Debt found, ticketed rather than promoted? no: it is on the board, not promoted. #1998 (no safe way to take a prod app offline for a restore under `selfHeal`, spec in #2013), #1997 (BACKUP-067 review follow-ups), #2015 (this spec's review follow-ups)

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
