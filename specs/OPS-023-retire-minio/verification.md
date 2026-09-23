---
tags: [spec, verification, templates]
created: "2026-09-22"
---

# Verification - OPS-023-retire-minio

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Inventory (2026-09-23, read-only)

The data held in each instance: prod `kubelab-backups` (the **MinIO** bucket) has 14 objects and 5.0 MiB, newest 2026-08-25; staging has 0 objects; the Beelink holds 88 KB. Both PVs are `local-path` with reclaim policy `Delete`. `pvc-backup` last succeeded on 2026-08-25 and every run since has failed silently.

Repo: 135 files, by category:
- K8s: 8 files;
- Ansible: 9, with **no teardown task** in `beelink_services`;
- SSOT: 7;
- toolkit: 12;
- tests: 18;
- Terraform DNS: 1 (`services.json` `minio`, `console.minio`);
- Uptime Kuma: 3 monitors;
- docs: about 40, split into current-state and historical;
- Makefile: `backup-pvc` plus dev lists;
- Renovate: 1 pin;
- a **third** deployment definition, `infra/stacks/services/data/minio/` (the local dev Compose stack).

`.github/`: none. Spec collisions: BACKUP-049 (the CronJob) and VPNACL-001 (`tag:hermes → MinIO`).

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/OPS-023-retire-minio/` -> `specs/archive/OPS-023-retire-minio/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
