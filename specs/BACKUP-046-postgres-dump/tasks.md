---
tags: [spec, tasks]
created: "2026-10-01"
---

# Tasks - BACKUP-046-postgres-dump

> TDD order. `[AC<n>]` maps a task to `proposal.md`; `[P]` marks a task with no unchecked dependency.

## Setup

- [x] Branch `feat/backup-046-postgres-dump` from master, worktree `~/Projects/kubelab-backup-046-wt`
- [x] Emergency copy taken and restore-checked (2026-10-01 06:51Z, see `verification.md`)
- [ ] Q1 and Q2 answered by the operator (the drafts below proceed on the proposals)

## PR 1 — Postgres reaches R2, and the static guard

- [ ] [P] [AC3] `tests/test_backup_pvc_coverage.py`: render the prod overlay, collect every PVC, fail on any with no ruling in `backup.sources.vps` or `backup.excluded.vps`. Expected red on master: `postgres-data`, `grafana-data`, `loki-data`, `crowdsec-db`, `crowdsec-config`.
- [ ] [AC3] Same file: every exclusion (volumes and claims) carries a non-empty `reason` and `tier: 3`; a claim exclusion carries `pvc: {namespace, claim}`. Red until the data below exists.
- [ ] [AC3] `common.yaml`: replace the "NOT here" prose with `backup.excluded.vps` entries for grafana, loki, crowdsec ×2 and `kube-system/traefik`; add `tier: 3` to the Beelink volume exclusions. Green.
- [ ] [P] [AC2] `tests/test_backup_sources.py`: `pg_dumpall` is a capture method next to `sqlite`, needs `pvc`, takes exactly `{deployment, container}`, and never co-exists with `sqlite`. Replace `test_the_retired_and_deferred_pvcs_stay_out`'s postgres half.
- [ ] [AC2] Test that runs the rendered capture script with a fake `kubectl` on `PATH`: a good dump is staged at `postgres/pg_dumpall.sql`; a dump missing the trailer, or a failing exec, exits non-zero with no sentinel; the claim's data directory is not copied. Red.
- [ ] [AC2] `node-backup-capture.sh.j2`: the `pg_dumpall` branch. Green.
- [ ] [AC1] `common.yaml`: declare `backup.sources.vps.postgres`.
- [ ] [AC6] Lesson: a deferral with an unwatched trigger is how the board went unbacked.
- [ ] `make test` green; PR opened as draft; reviews triaged.
- [ ] [AC1] After merge: deploy the role to the VPS, `make backup-node NODE=vps ENV=prod`, then list the snapshot's `postgres/` from R2.

## PR 2 — the live guard and the drill

- [ ] [P] [AC4] Test for `toolkit backup coverage`: a live claim with no ruling is reported, by namespace and name, and fails the command. Red.
- [ ] [AC4] Implement it in `toolkit/features/backup_destination.py` over the prod kubeconfig. Green, then run `make backup-coverage ENV=prod`.
- [ ] [P] [AC5] Test for the drill's comparison: equal counts pass, any differing table fails and is named, and the output never contains row contents. Red.
- [ ] [AC5] `toolkit backup drill-postgres` + `make backup-drill-postgres`: restic dump from R2, scratch container, row counts against live, cleanup on every exit path. Green, then run it on prod.
- [ ] [AC6] Runbook: "Restoring Postgres" and "Adding a stateful service" in `docs/runbooks/offsite-backup-restore.md`.

## Closing

- [ ] File the Vikunja attachments child of #1923 (Q2) and link it here.
- [ ] Delete the emergency copy in `~/backups/kubelab-emergency/` once AC1 and AC5 pass.
- [ ] `features.json` verifications non-vacuous; `verification.md` filled.
- [ ] Independent adversarial review, then archive and close #1111's Postgres half.
