---
tags: [spec, tasks]
created: "2026-10-01"
---

# Tasks - BACKUP-046-postgres-dump

> TDD order. `[AC<n>]` maps a task to `proposal.md`; `[P]` marks a task with no unchecked dependency.

## Setup

- [x] Branch `feat/backup-046-postgres-dump` from master, worktree `~/Projects/kubelab-backup-046-wt`
- [x] Emergency copy taken and restore-checked (2026-10-01 06:51Z, see `verification.md`)
- [ ] Q1 answered by the operator: keep `crowdsec-db` at its ratified tier 2 (the default applied here) or downgrade it. Q2 is #1981.

## PR 1 — Postgres reaches R2, and the static guard

- [x] [P] [AC3] `tests/test_backup_pvc_coverage.py`: render the prod overlay, collect every PVC, fail on any with no ruling in `backup.sources.vps` or `backup.excluded.vps`. Expected red on master: `postgres-data`, `grafana-data`, `loki-data`, `crowdsec-db`, `crowdsec-config`.
- [x] [AC3] Same file: every exclusion (volumes and claims) carries a non-empty `reason` and `tier: 3`; a claim exclusion carries `pvc: {namespace, claim}`. Red until the data below exists.
- [x] [AC3] `common.yaml`: replace the "NOT here" prose with `backup.excluded.vps` entries for grafana, loki, crowdsec ×2 and `kube-system/traefik`; add `tier: 3` to the Beelink volume exclusions. Green.
- [x] [P] [AC2] `tests/test_backup_sources.py`: `pg_dumpall` is a capture method next to `sqlite`, needs `pvc`, takes exactly `{deployment, container}`, and never co-exists with `sqlite`. Replace `test_the_retired_and_deferred_pvcs_stay_out`'s postgres half.
- [x] [AC2] Test that runs the rendered capture script with a fake `kubectl` on `PATH`: a good dump is staged at `postgres/pg_dumpall.sql`; a dump missing the trailer, or a failing exec, exits non-zero with no sentinel; the claim's data directory is not copied. Red.
- [x] [AC2] `node-backup-capture.sh.j2`: the `pg_dumpall` branch. Green.
- [x] [AC1] `common.yaml`: declare `backup.sources.vps.postgres`.
- [x] [AC6] Lesson: a deferral with an unwatched trigger is how the board went unbacked.
- [x] `make test` green (3147 passed, 2026-10-01); PR opened as draft; reviews triaged. ✓ 2026-10-01
- [x] [AC1] Before merge (sequenced after the #1979 review): `make backup ENV=prod`, `make backup-node NODE=vps ENV=prod`, then `make backup-drill-postgres ENV=prod` names the snapshot and its trailer. ✓ 2026-10-01, snapshot `00b263a5`

## PR 2 — the live guard and the drill

- [x] [P] [AC4] Test for `toolkit backup coverage`: a live claim with no ruling is reported, by namespace and name, and fails the command. Red.
- [x] [AC4] Implement it in `toolkit/features/backup_destination.py` over the prod kubeconfig. Green; `make backup-coverage ENV=prod` 2026-10-01: all 8 live claims ruled.
- [x] [P] [AC5] Test for the drill's comparison: a missing database or table fails and is named, a table empty in the restore but not live fails, a lower non-zero count passes and is shown, and the output never contains row contents. Red.
- [x] [AC5] `toolkit backup drill-postgres` + `make backup-drill-postgres`: restic dump from R2, scratch container, row counts against live, cleanup on every exit path. Green, then run it on prod. ✓ 2026-10-01, 34 tables
- [x] [AC6] Runbook: "Restoring Postgres" and "Adding a stateful service" in `docs/runbooks/offsite-backup-restore.md`.

## Closing

- [x] File the Vikunja attachments child of #1923 (Q2) and link it here: #1981. ✓ 2026-10-01
- [x] Delete the emergency copy in `~/backups/kubelab-emergency/` once AC1 and AC5 pass. ✓ 2026-10-01
- [x] `features.json` verifications non-vacuous; `verification.md` filled. ✓ 2026-10-01
- [ ] Independent adversarial review, then archive and close #1111's Postgres half.
