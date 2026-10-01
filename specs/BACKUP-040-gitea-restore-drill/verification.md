---
tags: [spec, verification]
created: "2026-10-01"
---

# Verification - BACKUP-040-gitea-restore-drill

## Evidence

### AC1, AC2: the prod drill (2026-10-01 15:0xZ)

`make backup-drill-gitea ENV=prod` from the workstation, against the Beelink repository in R2:

```text
[INFO] drill: snapshot af115af1 taken 2026-10-01T16:06:19.908967939+02:00
[SUCCESS] drill: restored 5 repositories in 5s
[SUCCESS] drill: git fsck --full passed on all 5 repositories
[SUCCESS] drill: the restored server answers, 8s after the restore began
[INFO]      manu/imagesensortool: 1 branch(es) restored, live 1
[INFO]      personal/resume: 8 branch(es) restored, live 7
[INFO]      teledyne/fae-brain: 13 branch(es) restored, live 13
[INFO]      teledyne/openkm-brain: 0 branch(es) restored, live 0
[INFO]      teledyne/projects-toolkit: 2 branch(es) restored, live 2
[SUCCESS] drill: snapshot af115af1 restores Gitea completely (5 repositories, 17s end to end)
```

rc 0, 23.7 s wall time including the toolkit's start. `personal/resume` has one branch more in the snapshot than live: it was deleted after the capture, which is the expected drift and the reason the check is "complete", never "equal".

**Measured RTO, first entry for epic #1923's table:** 17 s from the start of the restic restore to a complete check. Of that, the download and restore took 5 s (≈114 MB) and the server answered 8 s after the restore began. The real restore in the runbook adds a stop, a move and a start of the live container, measured in seconds, not minutes, at this size.

**The first run failed, as designed.** It stopped at CANNOT CHECK before restoring anything: `GET /repos/teledyne/openkm-brain/branches returned NoneType, expected a list`. Gitea answers an empty repository's branches with `null`. Fixed in `f133d87e`, recorded as lesson-499.

### AC2, AC3: the guards (tests and mutations)

`tests/test_gitea_drill.py` (19 tests) and `tests/test_gitea_client_pagination.py`. Each guard below was mutated out on a committed tree, and its test went red. The tree was restored with `git checkout HEAD --`.

| Guard mutated out | Result |
|---|---|
| repository missing on disk (`repo.lower() not in on_disk`) | 1 failed |
| restored with no branches (`live[repo] > 0 and not heads`) | 1 failed |
| head live does not know (`elif not known`) | 2 failed |
| head live cannot answer for is CANNOT CHECK (`known is None`) | 1 failed |
| failed read of the restored server is CANNOT CHECK (`body is _UNREAD`) | 1 failed |
| `git fsck` result ignored (`!= 0`, and `if broken`) | 1 failed each |

Live unreachable and live listing nothing are both CANNOT CHECK before any restore (`test_live_that_cannot_be_read_or_lists_nothing_is_cannot_check`). The token minted in the scratch server and the restored `app.ini` never reach the output (`test_a_good_restore_passes_names_the_snapshot_and_cleans_up`).

### AC4: nothing is left behind

Every run test asserts `_torn_down`: `docker rm -f -v` was called, docker no longer knows the container, and the directory is gone. That holds on a corrupt repository, a failed start, a server that never answers and a forged head. The teardown is `remove_scratch_container` from the Postgres drill: it reads back from docker and does not trust the exit code (#1988, lesson-498). The directory is wiped from a root container first, because Gitea runs as root at first start and writes into the bind mount.

On prod, after both runs: 49 docker volumes before and after, no `giteadrill-*` container, no `giteadrill-*` directory.

### AC5: runbook

`docs/runbooks/offsite-backup-restore.md`, "Gitea" under "Restoring — normal case": what the drill proves and the real restore on the Beelink. The real restore restores as root so the recorded owners come back (`1000:1000`, read from the live node), moves the broken data aside and keeps it until checked.

## Test status

- `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_gitea_drill.py tests/test_postgres_drill.py tests/test_gitea_client_pagination.py tests/test_make_env_default_is_reachable.py`: 111 passed.
- `make test` on `3be72f2e`: 3250 passed, 16 skipped, 2 xfailed, rc 0 (2026-10-01).

## Decisions made during implementation

- The drill runs on the workstation (Q1, pending the operator). It needs only docker, restic and the R2 credentials, and it runs unchanged on ace2.
- Live is read with the admin token, `read:repository` only. The restored server is read with a token minted inside it, because it has no network and its database holds no token the drill could know.
- The restored server is reached through `docker exec wget`, not a published port, so nothing on the host network can reach the copy.

## Promotion candidates

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/storage-backup/lesson-499-gitea-answers-an-empty-list-with-null.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the drill follows BACKUP-046's pattern, and epic #1923 already records the decision to prove restores
- [x] New pattern candidate for `00_meta/patterns/`? no: the scratch-container drill is specific to this repo's backup layout so far

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-040-gitea-restore-drill/` -> `specs/archive/BACKUP-040-gitea-restore-drill/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
