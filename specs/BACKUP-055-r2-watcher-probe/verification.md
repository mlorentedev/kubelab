---
tags: [spec, verification, templates]
created: "2026-09-25"
---

# Verification - BACKUP-055-r2-watcher-probe

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

### Task 1: the read-only token, measured 2026-09-26

The token is `kubelab-r2-watcher`, an account token with "Workers R2 Storage Bucket Item Read" on `kubelab-backups` only, no expiry and no IP filter. It is stored at `backup.r2.readonly_{access_key_id,secret_access_key}` in `common.enc.yaml`. The measurement ran from the workstation and printed only rc and restic output:

- `restic --no-lock --no-cache snapshots --json --latest 1`: rc=0 on all four repositories, n=1, 1.2 to 1.6 s each.
- `restic --no-lock --no-cache ls latest /opt/node-backup/staging`, non-recursive: rc=0, 2.2 to 2.9 s each. Direct children:
  - beelink `gitea`;
  - rpi3 `uptime_kuma`;
  - rpi4 `pihole`;
  - vps `authelia`, `headscale`, `n8n`.
  Every node also has `.capture-complete`. The recursive listing took 92 s on the Beelink (R3).
- Negative controls:
  - restic **without** `--no-lock` → rc=1 `unable to create lock in backend: client.PutObject: Access Denied`;
  - `aws s3 cp` into the bucket → rc=1 `AccessDenied` on PutObject.
  - A delete control was deliberately not run: the only real object to aim it at is a repository file, and a mistaken grant would have destroyed that repository.
- Conclusion: R2 is resolved. `--no-lock` is both required and sufficient, and AC2's refusal half is observed.

### AC4: generated targets (2026-09-26, `bc5996dd`)

- `make sync-r2-watcher-targets` writes `infra/k8s/base/services/r2-backup-watcher/targets.txt` on the first run and reports `unchanged` on the second. The render (`beelink beelink gitea`, `rpi3 rpi3 uptime_kuma`, `rpi4 rpi4 pihole`, `vps kubelab-vps authelia headscale n8n`) matches the repositories and directories measured in R2 in task 1.
- `tests/test_r2_watcher_targets.py`: 4 passed. Mutation: appending a line to the committed file turns `test_the_committed_targets_match_the_ssot` red with `... is stale. Regenerate it with make sync-r2-watcher-targets`. Restored from HEAD, it is green again. `toolkit sync r2-watcher-targets --check` reports `is current`.

### AC5: image pin (2026-09-26, `05034bb5`)

- `backup.watcher.image: restic/restic:0.19.1` in `IMAGE_SOURCES`, and `make sync-k8s-images` synced 11 tags. `restic/restic:0.19.1` exists on Docker Hub for amd64 and arm64.
- Mutation: bumping only the image to 0.19.2 turns `test_the_watcher_reads_with_the_restic_that_writes` red. Restoring it turns it green.

### AC1 (delivery): the watcher's Secret (2026-09-26, `3294d9b9`)

- `r2-backup-watcher-secrets` carries `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (both read-only) and `RESTIC_PASSWORD`, with no optional keys. A missing value refuses the apply.
- Mutation: pointing `AWS_ACCESS_KEY_ID` at the nodes' read-write `BACKUP_R2_ACCESS_KEY_ID` turns `test_the_write_credential_never_reaches_the_cluster` red.
- `make secrets-audit`: staging 58/58. Prod 80/84: the 4 missing are the `resume` Actions secrets, missing on master too, none of them this change's.

### AC1/AC3: the probe (2026-09-26, `db9ff02e`)

- `tests/test_r2_backup_watcher_probe.py`: 16 cases × {dash `sh`, busybox 1.37.0 `sh`, the image's shell} = 32 passed. Mutations:
  - a fleet verdict that ignores unhealthy nodes → 16 failed;
  - the `EXIT` trap removed → 8 failed (the missing-Secret and missing-targets paths go silent).
- **Real run** in `restic/restic:0.19.1`, `--read-only` rootfs with `/tmp` tmpfs, the read-only token, and the committed targets: 4 × `r2_backup_node` `healthy:1` with `sentinel:1` and `missing:[]`, then `r2_backup_health` `nodes:4 unhealthy:0 healthy:1`. rc=0, 16.4 s including container start.
- **Real red run**, same image, with mutated targets (`rpi3` plus a fake source `canary`, and a node `ghost` with no repository):
  - `rpi3` → `missing:["canary"] healthy:0 reason:"missing sources"`;
  - `ghost` → `readable:0 ... repository does not exist`;
  - fleet `nodes:2 unhealthy:2 healthy:0`; rc=1; 4.9 s.

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

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-055-r2-watcher-probe/` -> `specs/archive/BACKUP-055-r2-watcher-probe/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
