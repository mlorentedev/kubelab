---
id: lesson-465-a-read-only-restic-token-needs-no-lock-even-to-read
type: lesson
status: active
created: "2026-09-26"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, backup-055]
---

# A read-only object-store token cannot run restic's read commands unless they skip the lock

**Context**: BACKUP-055 gives the in-cluster R2 watcher an Object Read only token scoped to `kubelab-backups`. With that token the cluster can read every repository but can never `forget --prune` one.

**Problem**: restic takes a lock even to read. `snapshots` and `ls` write a non-exclusive lock object under `locks/` before they read anything. With the read-only token, `restic snapshots` fails with `unable to create lock in backend: client.PutObject: Access Denied`. That reads like a wrong token, but the token is doing exactly what it was scoped to do.

**Solution**: pass `--no-lock` to every read command, and `--no-cache` in a container that keeps nothing between runs. Measured 2026-09-26 against all four repositories: `snapshots` and `ls latest <dir>` return rc=0 in about 1 to 3 s each. Without `--no-lock` the same call fails, and `aws s3 cp` into the bucket is refused with `AccessDenied`. `restic check` cannot run this way, because it needs a real lock. Leave it to the nodes, which hold write access and already run it weekly.

**Rule**: when you give restic a credential that cannot write, `--no-lock` is part of the contract, not an optimisation. Prove the scope in both directions: the read succeeds with `--no-lock`, and both the locking read and a plain write are refused. Keep `restic ls` non-recursive on a directory (`ls latest /opt/node-backup/staging`), because a recursive listing of the Beelink's Gitea tree took 92 s.

**Tags**: `#restic` `#r2` `#backup-055` `#1572`
