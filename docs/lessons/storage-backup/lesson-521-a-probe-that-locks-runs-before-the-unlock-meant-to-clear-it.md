---
id: lesson-521-a-probe-that-locks-runs-before-the-unlock-meant-to-clear-it
type: lesson
status: active
created: "2026-10-04"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, locks, systemd]
---

# An `unlock` placed before the write is too late if a read before it takes a lock

**Context**: BACKUP-057 Q6 moved `forget --prune` out of the ship into its own unit,
`node-backup-prune.service`. Under the bucket lock a prune can now be killed mid-run
(timeout, reboot, OOM). restic 0.19.1 never skips a stale lock when it takes a new
one, so the ship gained a plain `restic unlock` right before `restic backup`.

**Problem**: the unit tests passed and so did the happy-path live runs. Then a prune was
`SIGKILL`ed on beelink while it held its exclusive lock, and the next ship failed with
exit 11 (`repository is already locked exclusively`). That ship never reached `unlock`.
The ship starts with two read-only checks, the `restic snapshots` reachability probe
and `restic cat config` for the repository id, and in restic every command that
opens a repository takes a lock unless told not to, reads included. The first run
after a killed prune died on the probe, and so would every later one.
The first kill attempt hid this: it landed before `forget` had locked, so the ship
succeeded and the test looked green.

**Solution**: `--no-lock` on both read-only checks, with `unlock` left right before `backup`
(`unlock` on a missing repository would fail the first ship before `init`). The
fake restic in `tests/test_node_backup_ship_script.py` now models a stale exclusive
lock: every locking call exits 11 until `unlock`, and `--no-lock` reads past it.
Live, against the real leftover lock: `successfully removed 1 locks`, then
`snapshot 627fad41 saved`.

**Rule**: when a run must clear stale state before it works, check every call that runs
before the cleanup, not only the one it protects. A crash test proves nothing until it
has seen the state it means to leave behind: wait for the lock (`restic list locks
--no-lock`) before you kill, or the test exercises only the easy case.

**Tags**: `#restic` `#backup-057` `#crash-test`
