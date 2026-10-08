---
id: lesson-538-restic-copy-locks-the-source-so-a-read-only-source-credential-needs-no-lock
type: lesson
status: active
created: "2026-10-08"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, credentials, testing]
---

# `restic copy` writes a lock into the source repository, so a read-only source credential fails unless the copy runs with `--no-lock`

**Context**: The first live `make backup-migrate NODE=vps ENV=prod` (BACKUP-057, 2026-10-08). The temporary token from lesson-529 has Object Read on `kubelab-backups`, the source, and Object Read & Write on `kubelab-backup-vps`, the destination.

**Problem**: The token passed its scope check and `init --copy-chunker-params --from-repo` wrote the destination's `config` and `keys`. Then `copy` failed with `Save(<lock/…>) failed: client.PutObject: Access Denied`. `copy` locks the source as well as the destination, and the token cannot write the source's `locks/`. The error carries no repository name, and the toolkit labelled it `copy into <dst> failed`, so it read as a destination problem.

The unit tests passed because their fake restic modelled the order of the steps but not the scope of the credential. Any command succeeded under any token.

Reproduced locally with restic 0.18.1: a source repository whose `locks/` directory is read-only fails the same way, and `--no-lock` copies every snapshot.

**Solution**: The copy runs as `restic copy --from-repo <src> --no-lock` (#2121). The test fake now refuses any command that opens the source without `--no-lock` under the temporary token, so the real constraint is modelled; without the fix, 7 tests fail. Without the source lock, a prune on the node could drop a pack mid-copy. The copy then fails, or the per-snapshot comparison finds the gap, and a re-run resumes.

**Rule**: A read-only credential is read-only only for commands that do not lock. Before handing restic, or any tool with advisory locks, a credential that cannot write, list which repositories each command locks. Make the test fake refuse what the real credential refuses. A fake that accepts every call under every token tests the call order and nothing about permissions.

Related: lesson-529 (why the copy needs a token of its own), lesson-521 (`--no-lock` on the ship's probes).

**Tags**: `#restic` `#r2` `#least-privilege` `#backup-057` `#test-fakes`
