---
tags: [spec, verification, templates]
created: "2026-09-29"
---

# Verification - BACKUP-058-no-silent-reinit

## Evidence

### AC1: restic 0.19.1 exit codes on R2 (2026-09-30, staging)

Setup: two throwaway Jobs created from `cronjob/r2-backup-watcher` in staging (`bk058-measure`, `bk058-measure2`), with `ownerReferences` stripped so the CronJob's history limit could not prune them before they were read (lesson-470). Both ran the pinned `restic/restic:0.19.1` image with the watcher's read-only R2 token and the repository password from the existing Secret. Only the container command was replaced. The Secret and the bucket were not touched, and both Jobs were deleted afterwards.

| Case | Command (`--no-lock --no-cache` on every call) | rc | First/last stderr line |
|---|---|---|---|
| missing repository | `snapshots -q` on `<prefix>/backup-058-does-not-exist` | **10** | `Fatal: repository does not exist: unable to open config file: Stat: The specified key does not exist.` |
| wrong password | `snapshots -q` on `beelink`, `RESTIC_PASSWORD` overridden | **12** | `Fatal: wrong password or no key found` |
| invalid credential | `snapshots -q` on `beelink`, `AWS_ACCESS_KEY_ID` overridden | none (hung) | Run 1, no stuck timeout: still running at the Job's 600 s deadline. Run 2, `--stuck-request-timeout 45s` inside `timeout 400`: killed at 400 s (rc 130), no Fatal line. Filed as #1939 (BACKUP-061). |
| `cat config --json`, all four repositories | read-only token | **0** ×4 | ids below |

- **R1 resolved:** R2 returns 10 for a missing repository, the same code as the local backend (measured 2026-09-29, restic 0.18.1). The design holds. An invalid credential never returns 10, so it can never reach `init`, which is the property AC3 needs; its slowness is #1939, not this spec.
- **R2 resolved:** `cat config` works with the read-only token under `--no-lock --no-cache`.

Repository IDs read on 2026-09-30 (not secrets; PR2 declares them in `backup.r2.repository_ids`):

| node | repository | id |
|---|---|---|
| beelink | `beelink` | `69e70ca8307994ac6076171f9dd7ce7b6681de24ad7c941b5be76b29a51133fa` |
| rpi3 | `rpi3` | `5ccc440d50e7b601cad0d292d366a32347a63998eca91fb78d910c4081e6641d` |
| rpi4 | `rpi4` | `a35c05eb848b35e6e8073d6d9df4feb16c8617caa46edb6ade46fe2c34cf9177` |
| vps | `kubelab-vps` | `2e9148a2db7f0881caba395c2d8f1308d9ef71f48cc8c1acfb950d40c9878409` |

This hand-built Job was a one-off: the only way to measure restic's exit codes against R2 was to call restic there directly. After PR2 the watcher prints each `repository_id` on every run, so reading the IDs again never needs a Job like this.

### AC2-AC7

- [ ] AC2 -> pending
- [ ] AC3 -> pending
- [ ] AC4 -> pending
- [ ] AC5 -> pending
- [ ] AC6 -> pending
- [ ] AC7 -> pending

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-058-no-silent-reinit/` -> `specs/archive/BACKUP-058-no-silent-reinit/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
