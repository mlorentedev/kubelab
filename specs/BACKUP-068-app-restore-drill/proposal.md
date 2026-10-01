---
id: "BACKUP-068-app-restore-drill"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-10-01"
issue: "mlorentedev/kubelab#1996"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-068: Authelia and n8n restore drill

## Why

<!-- from issue #1996: BACKUP-068: Authelia and n8n restore drill -->

Authelia and n8n are tier 1 in epic #1923's RTO table, and both keep encrypted data: Authelia's storage under `storage_encryption_key`, n8n's credentials under `encryption_key`, both in SOPS. `PRAGMA integrity_check` says the file is a database; it cannot say the SOPS key opens it. Until a restore has been started and read with the key we hold, these captures are not known to restore.

## What

`make backup-drill-apps ENV=prod` restores the VPS's newest snapshot of `authelia/` and `n8n/` into a private `0700` directory and, per service, passes only if:

1. `PRAGMA integrity_check` answers `ok` on the restored database.
2. **The restore is complete.** Every durable row live had when the snapshot was taken is in the restore, by id:
   - Authelia: `user_opaque_identifier` (the `sub` every OIDC client knows a user by), `user_preferences`, `totp_configurations`, `webauthn_credentials`. An opaque identifier must also come back with the same service, sector, user and value: a changed one is a new identity to every client. Contents are compared as digests in memory, never printed.
   - n8n: `workflow_entity` and `credentials_entity`.

   A row newer than the snapshot is INFO, by `created_at`/`createdAt` where the table has one and by an id above the restore's highest otherwise (both tables without a timestamp use `AUTOINCREMENT`). A row deleted since is INFO. Transient tables (sessions, logs, tokens) are not compared: the snapshot is up to four hours old and they turn over inside that.
3. **The key we hold opens it, in the image live runs, with no network.**
   - Authelia: `authelia storage encryption check --verbose` prints `Storage Encryption Key Validation: SUCCESS` with the SOPS key. It exits 0 on FAILURE too, so the text decides. Then the server starts on the restored database and `/api/health` answers `OK`.
   - n8n: the server starts on the restored data with the SOPS key and `/healthz` answers. The capture carries n8n's `config`, so a key that is not the data's aborts the start ("Mismatching encryption keys"), which the drill names. Then `export:credentials --all --decrypted --output=/dev/null` exits 0.

Live is read from the database files on the VPS with `sqlite3 -readonly` over SSH, the way the capture reads them, never by running the app's CLI in its pod. n8n's pod runs at about 365Mi of its 512Mi limit, and every `n8n` command starts a second n8n process (OPS-033, #1902). The live schema version is read the same way and shown beside the restore's.

The image comes from the live Deployment, never from values, so the drill tests the image that would have to open the data. Keys reach the containers only as `0600` files (`*_FILE`), never on argv or as `-e VALUE`. Containers run as the invoking user, and the container and the directory are removed on every exit path, read back.

## Out of scope

- Restoring into the live cluster: the runbook procedure covers it; the drill proves the data, not the cut-over.
- Transient tables (sessions, tokens, logs, bans): they turn over inside the snapshot interval.
- Running the app's CLI inside a live pod (OPS-033).
- Scheduling the drill: a scheduled drill is #1923's "drills on a schedule" line.

## Risks / open questions

- The restored n8n activates its workflows on start. `--network none` contains every outbound call; a schedule trigger can still run inside the scratch container against the scratch database, which harms nothing live.
- n8n's CLI prints `list`/`export` through its logger, and the live pod sets `N8N_LOG_LEVEL=warn`: the commands answer nothing with exit 0 (measured 2026-10-01, lesson-500). One more reason the drill reads live from the files; a live read that returns no durable rows at all is CANNOT CHECK.
- Authelia's file backend refuses an empty users map, so the scratch server gets one throwaway user whose argon2 hash is generated at drill time from a random password nobody sees.

## Acceptance criteria

- [ ] AC1: Authelia passes only when every durable live row present at snapshot time is restored (opaque identifiers unchanged), the encryption check prints SUCCESS, and the server answers healthy; rc 0 with FAILURE text is FAIL (tested).
- [ ] AC2: n8n passes only when the server starts on the restored data with the SOPS key, every workflow and credential present live at snapshot time is restored, and the credentials decrypt; a key mismatch is FAIL, a live read that fails or returns nothing is CANNOT CHECK (tested).
- [ ] AC3: no key on argv or in `-e VALUE`; the containers have no network; the container and the directory are removed on every exit path and a leftover makes the drill fail (tested).
- [ ] AC4: `make backup-drill-apps ENV=prod` passes against the newest R2 snapshot, and fails when given a wrong n8n key (prod transcript in `verification.md`).
- [ ] AC5: the runbook names the drill and the real restore procedure for both services.

## References

- Epic #1923; sister drills `toolkit/features/{postgres,gitea,headscale}_drill.py` (BACKUP-046, -065, -067).
- `docs/runbooks/offsite-backup-restore.md`.
