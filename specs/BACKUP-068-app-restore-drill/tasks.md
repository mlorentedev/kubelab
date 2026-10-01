---
tags: [spec, tasks]
created: "2026-10-01"
---

# Tasks - BACKUP-068-app-restore-drill

## Setup

- [x] Branch `feat/backup-068-app-restore-drill`, rebased onto master after BACKUP-067 (#1995) merged, for its SQLite and SSH helpers
- [x] Spike on prod data, torn down: Authelia's encryption check prints SUCCESS with the SOPS key and FAILURE (exit 0) with a random one; n8n's `config` key equals SOPS, the server is up in about 16 s, credentials decrypt
- [x] Live read decided from measurement, not the spike: the pod's CLI answers nothing at `warn` and would run a second n8n under a 512Mi limit at 365Mi (lesson-500), so live is read from the files over SSH

## Implementation

- [x] [AC1] [AC2] `compare()` and `rows_sql()`: tests for a missing row, newer by timestamp and by id, a missing id below the restore's highest, a changed identity, a deleted row, identity values hashed on read; then the implementation
- [x] [AC1] Authelia: tests for FAILURE text with exit 0, the key checked before the server starts, a server that never answers healthy; then `_prove_authelia`
- [x] [AC2] n8n: tests for a key that is not the data's (named, log line not printed), credentials that do not decrypt, a container that exited (not waited on), an answer that is not healthy; then `_prove_n8n`
- [x] [AC2] CANNOT CHECK: image unreadable or empty, no PV bound, live unreadable, live with no durable rows, no snapshot
- [x] [AC3] Key only as a `0600` file, never on argv; `--network none`; `--user`; teardown read back on every path; a leftover container or directory fails the drill
- [x] [AC4] `drill_apps()` resolves files, claims, keys and the SSH target from the SSOT; `toolkit backup drill-apps`; `make backup-drill-apps`; `ENV_TARGETS`
- [x] Mutation-check every guard
- [x] [AC4] Prod run, and a prod run with random keys that must fail
- [x] [AC5] Runbook section; lesson-500; #1998 for the step the runbook cannot do safely yet

## Closing

- [x] `make test` green
- [x] Prod transcripts in `verification.md`
- [ ] `dotf spec review` by a different model
