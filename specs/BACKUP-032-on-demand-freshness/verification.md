---
tags: [spec, verification, templates]
created: "2026-10-01"
---

# Verification - BACKUP-032-on-demand-freshness

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] **AC1** -> commit `<hash>` / test `<name>`
- [ ] **AC2** -> commit `<hash>` / test `<name>`
- [ ] **AC3** -> commit `<hash>` / test `<name>`
- [ ] **AC4** -> commit `<hash>` / test `<name>`
- [ ] **AC5** -> commit `<hash>` / test `<name>`
- [ ] **AC6** -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Measurements (2026-10-02)

- **Time format.** Read through the toolkit (`backup_destination.coverage` with a recording `run`), shape only: beelink, rpi3 and rpi4 answer `YYYY-MM-DDTHH:MM:SS.<8 or 9 digits>+HH:MM`, and vps answers `...<9 digits>Z`. The fraction length varies (Go trims trailing zeros), and the offset is the source node's.
- **Pinned image (`restic/restic:0.19.1`, BusyBox v1.37.0).** `date -u -d "YYYY-MM-DD HH:MM:SS" +%s` and `date -u -d @<epoch>` work, `sed -E` works, and `nc -z -w 2` answers rc 0 for an open port, rc 1 for a refused one and rc 1 after the timeout for a blackholed address. `date -d` does not take an ISO string with an offset, and `$((08))` is an arithmetic error in BusyBox and dash, so the probe splits the offset with `sed -E` and strips its leading zero.
- **Reachability: the pod probe was replaced, by decision.** The task asked for `nc` from a pod in prod. No codified path runs an ad-hoc pod, and a hand-typed `kubectl run` in prod is what the repo rules forbid. It is replaced by three pieces of evidence:
  1. The IaC: port 22/tcp is in `base_system`'s fleet-wide `firewall_allowed_ports` and in `networking.firewall.vps_inbound`, and `sshd_config.j2` listens on `0.0.0.0`.
  2. A staging watcher run before merge. Staging runs on ace1, which is LAN-adjacent to beelink and rpi4, so that run proves the probe works, not prod reachability.
  3. AC5 after merge, the real measurement from the VPS pod, with vps and rpi3 as the positive control.

## Decisions made during implementation

- `class` is emitted on every `r2_backup_node` line and AC1 now names it (#2035 review, recorded on #485): the freshness rule filters on it, and a filter on a label nobody emits pages forever through `noDataState`.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-032-on-demand-freshness/` -> `specs/archive/BACKUP-032-on-demand-freshness/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
