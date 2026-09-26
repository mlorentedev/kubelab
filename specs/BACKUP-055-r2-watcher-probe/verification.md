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
