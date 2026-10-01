---
id: "BACKUP-040-gitea-restore-drill"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-10-01"
issue: "mlorentedev/kubelab#487"
tags: [spec, proposal, backup, gitea]
template_version: "1.0"
---

# BACKUP-040: Gitea restore drill

## Why

<!-- from issue #487: BACKUP-040: Validate backup restore e2e — run restore on test target, verify data integrit -->

Gitea on the Beelink is now where important repositories are developed, and its R2 backup has never been restored. The only restore ever run was manual, on 2026-08-22, when Gitea held no repositories (#1923). A backup nobody has restored is a hope: `restic check` proves the repository is consistent, not that what it holds brings Gitea back. This is #1090's gate ("a repository pushed to Gitea has survived one exercised restore") and the first "prove the restore" item of epic #1923.

## What

`make backup-drill-gitea ENV=prod` restores the newest Beelink snapshot from R2 into a private temp directory on the machine running it, and passes only if the restore brings Gitea back whole:

1. **Every repository is intact on disk.** `git fsck --full` runs on every bare repository under the restored `git/repositories/`. A failure names the repository.
2. **The restored server starts and serves them.** The Gitea image pinned in `common.yaml` starts on the restored `/data` with `--network none`, so it cannot reach live services, mirrors or webhooks. Its API must answer. A token minted inside the scratch container lists the repositories.
3. **The restore is complete against live.** The drill reads live Gitea with the admin token (`read:repository`, never a write credential):
   - every repository live lists exists in the restore, on disk and in the restored database;
   - no repository that has branches live came back with zero refs;
   - every branch head in the restore is a commit that live knows (`GET /repos/{o}/{r}/git/commits/{sha}`).

   Like the Postgres drill, it reports "complete", never "equal". The snapshot can be hours older than live, so a newer push is expected and is not a failure.
4. **It leaves nothing behind.** The container is removed with its volumes (`docker rm -f -v`, lesson-498), and the temp directory is removed, on every exit path. Only names and counts are printed. The restored `gitea.db` and `app.ini` hold password hashes and secrets.

The drill also records how long the restore takes (download, fsck, time until the API answers), which is the first measured RTO for epic #1923's target table.

## Out of scope

- LFS objects (#1922 covers mirrors and asks whether they carry LFS).
- A scheduled drill and the "drill overdue" push monitor (#1211, epic #1923 item 4).
- Restoring into live Gitea. This drill never writes to the Beelink.
- Issues, pull requests and wiki content beyond "the database restores and the server starts". A comparison of every issue count is a later refinement if this drill passes.

## Risks / open questions

- **Q1 [AGENT-DRAFT — review before archive]:** the epic names ace2 as the target for this restore, and its item 4 names an ephemeral namespace on staging for the automated drill. This spec runs the drill on the operator's workstation, because ace2 is on-demand and the drill only needs docker, restic and the R2 credentials, which the workstation already has. The command is host-agnostic, so it runs unchanged on ace2. Accept running on the workstation, or require an ace2 run before archive?
- The restored data is a full copy of the forge, private repositories included. It stays in a `0700` temp directory and is deleted in a `finally`. A crash that kills the process (SIGKILL, power loss) leaves it behind. The same applies to the Postgres drill.
- Gitea may try to write to `/data` on start (queues, indexers, sessions). That is the scratch copy, so writes are harmless, but a start that blocks on a missing directory would read as a failed restore. Observe it on the first live run.

## Acceptance criteria

- [ ] AC1: `make backup-drill-gitea ENV=prod` restores the newest Beelink snapshot from R2, runs `git fsck --full` on every restored repository, and names any that fail.
- [ ] AC2: The pinned Gitea image starts on the restored data with no network. Its API lists every repository that live lists. Every repository with branches live has refs in the restore, and every restored branch head is a commit live knows. The drill fails and names the repository otherwise.
- [ ] AC3: The drill fails as CANNOT CHECK, never passes, when live cannot be read or lists no repositories, and when no snapshot is readable.
- [ ] AC4: On every exit path the container, its volumes and the temp directory are gone. Tests pin it, and the transcript in `verification.md` shows it measured.
- [ ] AC5: `docs/runbooks/offsite-backup-restore.md` documents the Gitea drill, and how to restore Gitea for real from the same snapshot. `verification.md` records the drill's transcript and measured RTO.

## References

- Epic #1923 (proven restores); #1090 (the gate this closes); #1211 (scheduling); #1922 (mirrors, LFS)
- `toolkit/features/postgres_drill.py` (BACKUP-046), the drill this one follows
- lesson-498 (`docker rm` without `-v`), lesson-416 (an empty answer is not a pass)
