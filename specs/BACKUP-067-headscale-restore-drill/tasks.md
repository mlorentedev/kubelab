---
tags: [spec, tasks]
created: "2026-10-01"
---

# Tasks - BACKUP-067-headscale-restore-drill

## Setup

- [x] Branch `feat/backup-067-headscale-restore-drill`, stacked on BACKUP-040 (#1993) for `staging_dir`; rebased onto master once #1993 merges
- [x] Spike on prod data, torn down: v0.28.0 starts with `--network none` and `--user`, lists 12 nodes and 4 users; key hashes match live
- [ ] Q1 and Q2 answered by the operator before archive

## Implementation

- [x] [AC2] `compare()`: tests for missing node, changed machine key, missing user, newer and deleted entries reported, then the implementation
- [x] [AC1] Integrity check and key comparison: tests for a missing file, a bad database, a key mismatch, then the implementation
- [x] [AC3] CANNOT CHECK: tests for failed or empty live nodes, users and key hashes, and no snapshot
- [x] [AC4] Teardown: tests for every exit path (bad database, failed start, never answers, mismatch), read back
- [x] [AC1] `drill_headscale()` resolves repo, image, volume, SSH target and staging dir from the SSOT; `toolkit backup drill-headscale`; `make backup-drill-headscale`
- [x] Mutation-check every guard
- [x] [AC5] Runbook section; lesson if the drill finds anything

## Closing

- [ ] `make test` green
- [x] Prod run: transcript and RTO in `verification.md`
- [ ] `dotf spec review` by a different model
