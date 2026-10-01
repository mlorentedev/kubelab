---
id: "BACKUP-071-ace2-drills"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-01"
issue: "mlorentedev/kubelab#2011"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, backup]
template_version: "1.0"
---

# BACKUP-071: the restore drills run on ace2, with secrets injected per run

## Why

<!-- from issue #2011: BACKUP-071: run the restore drills on ace2 with secrets injected per run, no age key on the node -->

The operator ruled on 2026-10-01 that the Gitea (BACKUP-040, #487) and Headscale (BACKUP-067, #1994) restore drills must run on ace2 before those specs archive. A run on the workstation does not count. They also ruled on the method: ace2 holds no SOPS age key, and the workstation decrypts only the values one drill needs and injects them into that run. Today no drill can run on ace2. ace2 has docker and make, but no kubelab checkout, poetry, restic or toolkit. A remote `DOCKER_HOST` cannot stand in either: the drills restore into a local directory and then `docker run -v` it, so the daemon has to share the filesystem restic wrote to. Until this ships, both archives stay blocked.

## What

1. **`make backup-drill-gitea HOST=ace2` and `make backup-drill-headscale HOST=ace2`** run the drill on ace2 and print the same names, ids and counts as a local run. Without `HOST`, nothing changes.
2. **The workstation resolves, ace2 executes.**
   - The workstation reads SOPS and the merged config and builds one JSON payload with everything the drill takes: restic repository and environment, image, staging directory, the Gitea admin token where the drill needs it, and the live reads (below).
   - It sends the payload to `toolkit backup drill-<x> --inputs-stdin` on ace2 over the ssh session's **stdin**. A secret never appears in argv (visible in `ps` on both ends), in a remote shell's environment assignment, or in a file.
   - The remote drill path never constructs a `ConfigurationManager` and reads no config: it calls the same `run_drill` a local run calls, on the payload alone. The toolkit process still loads the `dev` config at import (`toolkit/config/settings.py`, #2021), so the guarantee that ace2 decrypts nothing rests on ace2 having neither `sops` on the non-interactive PATH nor an age key. Both are checked by the AC1 gate, and provisioning fails if the key appears.
3. **Live reads stay on the workstation.** For Headscale, the live node and user lists and the hashes of the live key files need ssh and `sudo -n` on the VPS. The workstation reads them and passes them as inputs; none of them is a secret. ace2 gets no VPS credential and no forwarded agent. `headscale_drill.run_drill` is split at that seam: `read_live(...)` on the workstation, and the restore and compare against a given live state on whichever host runs it. A local run calls both, in the same order as today.
4. **ace2 runs the code being tested, not master.**
   - The `dev_node` role owns a dedicated checkout at `~/.local/share/kubelab-drill`, separate from any developer clone, plus the runtime: pinned restic, pinned poetry, and docker access for the dev user.
   - Each run fetches and checks out, detached, the exact commit the workstation runs, then runs `make worktree-init`.
   - The workstation refuses to start a remote run from a dirty tree or a commit `origin` does not have. Each case is CANNOT CHECK, naming the reason. This makes the evidence a fact about a commit, and it lets a branch prove itself on ace2 before it merges.
5. **restic is installed by one set of tasks.** `node_backup`'s pinned, checksum-verified install moves to a tasks file that both `node_backup` and `dev_node` include, with the version still read from `backup.r2.restic_version`. It is not copied.

## Out of scope

- Running the Postgres and app drills (`drill-postgres`, `drill-apps`) on ace2. The payload shape covers them, but nothing asks for it. Their live reads go through kubectl and the VPS, and wiring them means the same split per drill.
- Keeping the Gitea admin token off ace2. The issue allows it to travel. Comparing live on the workstation instead would split `gitea_drill.run_drill` into restore-facts and compare. Recorded as a possible later tightening, not built here.
- Scheduling drills (cron, CI). This makes a run possible on ace2; how often it runs is a separate decision.
- Any change to the restored data's handling. The restored `app.ini`, password hashes and SSH host keys are the drill's subject, and the existing unconditional teardown removes them.

## Risks / open questions

- **First `make worktree-init` on ace2 re-resolves `poetry.lock` against live PyPI** (DEBT-015, #1128: the lock is gitignored). The setproctitle truncation seen on 2026-10-01 would hit this too. The checkout persists across runs, so later runs reuse the venv and `poetry check --lock` passes until `pyproject.toml` changes. If it fails, the remote run reports the init failure as CANNOT CHECK. It must not continue on a stale venv.
- **A non-interactive ssh session does not see `~/.local/bin` or mise's shims.** Its PATH is `/etc/environment` verbatim (the reason `dev_node_local_bin_wrapped` exists). poetry has to be exposed the same way as `dotf`, or the run calls it by absolute path. The baseline shows only `/usr/bin/python3` there.
- **The dev user must reach docker without sudo.** Measured: `manu` is in `docker` on ace2 today. The drills call `docker` directly. Provisioning asserts group membership instead of assuming it; a non-interactive `sudo` prompt would hang an ssh run.
- **The Gitea drill's live side needs Beelink up.** This is not new: it is true locally too, and the drill already reports it as CANNOT CHECK.
- **The payload holds secrets in transit.** It travels inside the ssh session (encrypted), is read once from stdin into memory, and is never logged. The remote entrypoint must not echo it on a parse error. A test feeds a malformed payload and asserts that no value from it reaches stderr.
- **AC3 covers what the toolkit injects, not the restored data.** A file under the drill's work directory holding a restored secret (Gitea's `app.ini`) is the drill working as designed. AC3 checks that the restic password, the R2 keys and the Gitea token are never written to disk. Removing the restored data stays with the drills' existing teardown and its tests.

## Acceptance criteria

- [ ] **AC1** `make provision NODE=ace2 ENV=prod` reports `changed=0` on its second run. ace2 then has restic at the pinned version, poetry, the drill checkout and docker access for the dev user, and no SOPS age key and no `sops` on the non-interactive PATH: `ssh ace2 'test ! -e ~/.config/sops/age/keys.txt && ! command -v sops'` exits 0. `node_backup` and `dev_node` include the same restic tasks file. A test fails if either role grows its own copy.
- [ ] **AC2** `make backup-drill-gitea HOST=ace2` and `make backup-drill-headscale HOST=ace2` pass from a pushed branch and print only names, ids and counts, as they do locally. Each refuses to start from a dirty tree, or from a commit `origin` lacks, with CANNOT CHECK naming the reason.
- [ ] **AC3** Unit tests, against the command the toolkit builds and the remote entrypoint with a fake runner:
  - no injected value (restic password, R2 keys, Gitea token) appears in the ssh argv;
  - the payload travels on stdin;
  - the remote entrypoint's drill path never builds a `ConfigurationManager` (the import-time `dev` load is #2021's, and ace2 is kept unable to decrypt by AC1);
  - after a run, no file under the work directory contains an injected value;
  - a malformed payload fails without echoing any of its values.
- [ ] **AC4** The `verification.md` of BACKUP-040 and of BACKUP-067 carries its ace2 run (host, commit, snapshot, result). That unblocks their archive PRs.
- [ ] **AC5** `docs/runbooks/offsite-backup-restore.md` explains how to run a drill on ace2: `HOST=ace2`, what has to be pushed first, and what travels to ace2 and what does not.

## References

- Bitácora board: #2011. Blocks the archives of #487 (BACKUP-040) and #1994 (BACKUP-067).
- Operator decisions, 2026-10-01: ace2 runs required (comments on #487 and #1994); per-run secrets (#2011).
- ADR-058 D1: ace2 is the developer node, so a checkout there is sanctioned (the "never clone on deployment targets" rule does not apply).
- `docs/runbooks/offsite-backup-restore.md`; drills in `toolkit/features/{gitea,headscale}_drill.py`.
- Lesson-416 (a check that compares nothing passes): every remote failure is CANNOT CHECK, never a pass.
