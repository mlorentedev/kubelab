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

- **Authelia**
  - `PRAGMA integrity_check` answers `ok` on `db.sqlite3`;
  - `authelia storage encryption check --verbose` with the SOPS key prints `Storage Encryption Key Validation: SUCCESS`. The command exits 0 on FAILURE too, so the text decides, never the exit code;
  - the restored schema version equals live's (`authelia storage schema-info` on both);
  - the image live runs starts on the restored database with no network and `/api/health` answers `OK`.
- **n8n**
  - `PRAGMA integrity_check` answers `ok` on `database.sqlite`;
  - the image live runs starts on the restored data with the SOPS key and no network, and `/healthz` answers. The capture carries n8n's `config`, so a SOPS key that differs from the data's aborts the start ("Mismatching encryption keys"), which the drill reports as such;
  - every workflow live had when the snapshot was taken is in the restore, by id. A workflow newer than the snapshot is INFO, one deleted since is INFO;
  - every credential decrypts: `export:credentials --all --decrypted` exits 0 with its output sent to `/dev/null`.

What is **not** compared, and why: Authelia's rows (TOTP, WebAuthn, consent, preferences). Live Authelia has no `sqlite3` binary and its export commands print secrets, so the restore's per-table row counts are shown, not compared. n8n's credentials are checked for decryption, not compared with live by id.

The image is read from the live Deployment, never from values, so the drill always tests the image that would have to open the data. Keys reach the containers only as `0600` files (`*_FILE`), never on argv or as `-e VALUE`. Containers run as the invoking user, and the container and the directory are removed on every exit path, read back.

## Out of scope

- Restoring into the live cluster: the runbook procedure covers it; the drill proves the data, not the cut-over.
- Comparing Authelia rows with live (see above).
- Scheduling the drill: a scheduled drill is #1923's "drills on a schedule" line.

## Risks / open questions

- The restored n8n activates its workflows on start. `--network none` contains every outbound call; a schedule trigger can still run inside the scratch container against the scratch database, which harms nothing live.
- n8n's CLI prints `list`/`export` through its logger, and the live pod sets `N8N_LOG_LEVEL=warn`: the commands answer nothing with exit 0 (measured 2026-10-01, lesson-500). The drill forces `info` on every read and treats an empty live list as CANNOT CHECK.
- Authelia's file backend refuses an empty users map, so the scratch server gets one throwaway user whose argon2 hash is generated at drill time from a random password nobody sees.

## Acceptance criteria

- [ ] AC1: Authelia passes only on a SUCCESS text from the encryption check, a schema version equal to live's and a healthy server; rc 0 with FAILURE text is FAIL (tested).
- [ ] AC2: n8n passes only when the server starts on the restored data with the SOPS key, every live workflow present at snapshot time is restored, and the credentials decrypt; a key mismatch is FAIL, an unreadable live list is CANNOT CHECK (tested).
- [ ] AC3: no key on argv or in `-e VALUE`; the containers have no network; the container and the directory are removed on every exit path and a leftover makes the drill fail (tested).
- [ ] AC4: `make backup-drill-apps ENV=prod` passes against the newest R2 snapshot, and fails when given a wrong n8n key (prod transcript in `verification.md`).
- [ ] AC5: the runbook names the drill and the real restore procedure for both services.

## References

- Epic #1923; sister drills `toolkit/features/{postgres,gitea,headscale}_drill.py` (BACKUP-046, -065, -067).
- `docs/runbooks/offsite-backup-restore.md`.
