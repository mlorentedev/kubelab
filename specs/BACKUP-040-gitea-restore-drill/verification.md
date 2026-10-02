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

### AC1, AC2: the prod drill on ace2 (2026-10-01, BACKUP-071)

The operator required an ace2 run before archive (#487). Run with
`make backup-drill-gitea HOST=ace2 ENV=prod` from branch
`feat/backup-071-ace2-drills` at `86f6d16a`, pushed. The workstation resolved the
restic environment and the admin token from SOPS and sent them on the ssh
session's stdin; ace2 restored, started the scratch server and read live Gitea
itself.

```text
gitea restore drill on ace2 (prod)
[INFO] drill: running gitea on manu@100.64.0.5 at 86f6d16aeaa4
[INFO] drill: snapshot 0b556cbb taken 2026-10-02T00:29:50.730823192+02:00
[SUCCESS] drill: restored 5 repositories in 6s
[SUCCESS] drill: git fsck --full passed on all 5 repositories
[SUCCESS] drill: the restored server answers, 14s after the restore began
[INFO]      manu/imagesensortool: 1 branch(es) restored, live 1
[INFO]      personal/resume: 6 branch(es) restored, live 6
[INFO]      teledyne/fae-brain: 13 branch(es) restored, live 13
[INFO]      teledyne/openkm-brain: 0 branch(es) restored, live 0
[INFO]      teledyne/projects-toolkit: 2 branch(es) restored, live 2
[SUCCESS] drill: snapshot 0b556cbb restores Gitea completely (5 repositories, 22s end to end)
rc=0
```

The `make worktree-init` output between the first two lines is omitted. Two
`SOPS is not installed` warnings came from the toolkit's import, not from the
drill (#2021, TOOL-097). Afterwards on ace2: no `giteadrill-*` container and no
`giteadrill-*` directory under `/tmp`.

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

On prod, after both runs: 49 docker volumes before and after, no `giteadrill-*` container, no `giteadrill-*` directory. The volume count alone could not show a leftover anonymous volume, so the image was checked directly: `docker image inspect -f '{{json .Config.Volumes}}' gitea/gitea:1.25.5` answers `{"/data":{}}`, which the bind mount covers. The scratch server therefore creates no anonymous volume, and the Gitea fake lists none.

### AC5: runbook

`docs/runbooks/offsite-backup-restore.md`, "Gitea" under "Restoring — normal case": what the drill proves and the real restore on the Beelink. The real restore restores as root so the recorded owners come back (`1000:1000`, read from the live node), moves the broken data aside and keeps it until checked.

## Test status

- `poetry run pytest -q -p no:cacheprovider --no-cov tests/test_gitea_drill.py tests/test_postgres_drill.py tests/test_gitea_client_pagination.py tests/test_make_env_default_is_reachable.py`: 111 passed.
- `make test` on `3be72f2e`: 3250 passed, 16 skipped, 2 xfailed, rc 0 (2026-10-01).
- `make test` on master `4d995e69` (with BACKUP-071 merged), before the archive: 3484 passed, 16 skipped, 154 deselected, 2 xfailed, rc 0 (2026-10-01).
- After the review dispositions: `tests/test_gitea_drill.py tests/test_drill_remote.py` 61 passed; after round 3, `tests/test_gitea_drill.py` 32 passed.

## Review dispositions (`review.md` at `8033834e`, FAIL)

The contract set (`proposal.md`, `tasks.md`) is unchanged. `features.json` gained only `state` and `evidence`. The fixes are code and tests:

| Finding | Disposition | Evidence |
|---|---|---|
| Major: `return ok and removed and wiped` enforced by no test | Applied (`5d489bd2`). `test_a_complete_restore_whose_container_is_left_behind_fails` makes `docker rm` leave the container; `test_a_complete_restore_that_leaves_its_data_on_disk_fails` makes the wipe and `rmtree` leave the directory. Both assert that the restore itself passed, so the failure comes from the teardown. | `return ok`: 2 failed. `return ok and wiped`: 1 failed. `return ok and removed`: 1 failed. |
| Major: no-snapshot branch untested and not labelled CANNOT CHECK | Applied. The message is `drill: CANNOT CHECK — no snapshot readable in <repo>`, as in the Headscale drill. A malformed snapshot list, which raised before, now takes the same branch. `test_no_readable_snapshot_is_cannot_check` covers restic failing, an empty list and malformed JSON, and asserts that nothing is restored. | Label removed: 3 failed. `except ValueError` → `except KeyError`: 1 failed. |
| Minor: `_paginate` raised on a non-list body | Applied. A page that is not the list the endpoint returns (`{"data": null}`, a dict without the key, a string, a number) is an unread page, and the caller already reports that as CANNOT CHECK. A top-level `null` is still an empty collection (lesson-499). Three tests cover it. | `isinstance(batch, list)` → `batch is None`: 2 failed. |
| Minor: a repository renamed since the snapshot fails the drill | Accepted as a limit and documented in the module docstring. The failure is a false alarm, never a false pass, and the next capture clears it. Telling a rename from a loss would need the snapshot's own database as the reference, which is a different drill. | Docstring, `toolkit/features/gitea_drill.py`. |
| Minor: a repository in the restored DB but gone from live and from disk is not checked | Accepted as a limit and documented in the module docstring. The drill proves the restore brings back what live has. A repository live has deleted is not something a restore owes. | Docstring, same file. |
| Minor: `_restore_and_check` over the complexity bar | Carried by #2015 item 3, which extracts the shared restore → compare → prove phases for all four drills under their behavioural tests. | #2015 (open). |

## Review dispositions, round 3 (`review.md` at `dbdbfc88`, PASS-WITH-GAPS)

| Finding | Disposition | Evidence |
|---|---|---|
| Minor: the "restic could not restore" return has no named test | Applied (`a2479019`): `test_a_restore_restic_cannot_finish_fails_names_it_and_never_starts_a_server`. | `if rc != 0 or not data.is_dir():` → `if False:`: 1 failed, 31 passed. |
| Minor: complexity | Carried by #2015 item 3, as in round 2. | #2015 (open). |
| Minor: `snapshots[-1]` here, `snapshots[0]` in the Postgres drill | Carried by #2015 item 3. Today one snapshot per run holds every source, so the two agree. The shared restore phase that item extracts will choose the snapshot once, for all four drills. | Comment on #2015. |
| Minor: the two documented limits | Accepted, as in round 2. | Module docstring. |

## Decisions made during implementation

- Where the drill runs (Q1): the operator required ace2. The command needs only docker, restic and the inputs, so `HOST=ace2` runs the same drill there (BACKUP-071), and the ace2 run is the evidence of record.
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
