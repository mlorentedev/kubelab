---
tags: [spec, tasks]
created: "2026-10-01"
---

# Tasks - BACKUP-040-gitea-restore-drill

> TDD order. `[AC<n>]` maps a task to `proposal.md`; `[P]` marks a task with no unchecked dependency.

## Setup

- [x] Branch `feat/backup-040-gitea-restore-drill`, worktree `~/Projects/kubelab-backup-040-wt`, stacked on BACKUP-046 PR 2 (#1988) for the shared drill helpers. ✓ 2026-10-01
- [x] `proposal.md` complete, acceptance criteria testable. ✓ 2026-10-01
- [x] Q1 answered by the operator: require an ace2 run before archive. Done by BACKUP-071 (#2024). ✓ 2026-10-01

## Implementation

- [x] [P] [AC2] `tests/test_gitea_drill.py`: `compare` fails and names a repository missing on disk, missing from the restored database, emptied, or whose head live does not know; a lower or higher branch count passes; a head live cannot answer for is CANNOT CHECK. Red, then `toolkit/features/gitea_drill.py:compare`. Green.
- [x] [AC2] `GiteaClient.list_branches` and `commit_exists`, `read:repository`, in `ADMIN_METHODS`.
- [x] [AC1] [AC2] `run_drill`: restic restore of the Gitea subtree, `git fsck --full` per repository, the pinned image with `--network none`, a token minted inside, the restored API read over `docker exec`. Tests: a corrupt repository never starts a server; a server that fails to start or never answers fails; a forged head fails. Green.
- [x] [AC3] Live unreachable, or listing no repositories, is CANNOT CHECK before anything is restored; a failed read of the restored server is CANNOT CHECK. Green.
- [x] [AC4] Teardown: `remove_scratch_container` (shared with the Postgres drill, read back, #1988) and a root-run wipe of the bind-mounted directory, on every exit path. `_torn_down` asserted in every run test. Green.
- [x] `toolkit backup drill-gitea` + `make backup-drill-gitea` (prod by default, in the env-default table).
- [x] [AC2] First prod run found Gitea's `null` for an empty repository's branches (lesson-499): both paginators treat `null` as empty, a failed read stays CANNOT CHECK. Green, rerun passed. ✓ 2026-10-01
- [x] [AC5] Runbook: "Gitea" under "Restoring — normal case": the drill, and the real restore on the Beelink. ✓ 2026-10-01

## Closing

- [x] `features.json` verifications non-vacuous; `verification.md` filled with the prod transcript and the RTO. ✓ 2026-10-01
- [x] Lesson-499 written and indexed. ✓ 2026-10-01
- [ ] Independent adversarial review, then archive; the gate in #1090 ("a repository pushed to Gitea has survived one exercised restore") is met by this drill.
