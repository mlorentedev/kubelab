---
tags: [spec, verification, templates]
created: "2026-08-19"
---

# Verification - BACKUP-049-pvc-backup-heartbeat

## Abandoned

Abandoned 2026-10-03 (DEBT-019, #2034): the subject no longer exists. The in-cluster `pvc-backup` CronJob whose missing heartbeat this spec targets was removed by OPS-023 PR 1; prod PVCs are now backed up from the node by `node_backup`. A run that never starts is caught by the Uptime Kuma push heartbeat that `node_backup` sends on every completed ship (BACKUP-044 AC9; the always-on VPS, which holds the prod PVCs). On on-demand nodes, where that heartbeat is muted, the BACKUP-032 rule `backup032-on-demand-freshness` catches it from R2. `obs015-r2-backup-health` adds integrity and coverage checks on R2. kubelab#1171 is closed.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? no: abandoned before implementation; the reason above is the only record needed
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: abandoned before implementation; the reason above is the only record needed
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: abandoned before implementation; the reason above is the only record needed

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-049-pvc-backup-heartbeat/` -> `specs/archive/BACKUP-049-pvc-backup-heartbeat/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
