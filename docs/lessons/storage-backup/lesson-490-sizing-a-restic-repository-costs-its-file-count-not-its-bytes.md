---
id: lesson-490-sizing-a-restic-repository-costs-its-file-count-not-its-bytes
type: lesson
status: active
created: "2026-09-30"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, observability]
---

# Sizing a restic repository costs its file count, not its bytes

**Context**: BACKUP-057 needs each node's repository size to decide whether a 30-day bucket lock fits R2's free tier. The R2 watcher already opens all four repositories every 6 hours, so it gained one more call: `restic stats --mode raw-data --no-lock --no-cache --json`, under the same 60 s `RESTIC_TIMEOUT` as its other calls.

**Problem**: The Beelink's size came back `null` on the first staging run, killed by the timeout. Its repository is not the biggest. Measured 2026-09-30:

| Node | Stored bytes | `stats` took |
|---|---:|---:|
| beelink | 61 MB | 143 s |
| rpi3 | 53 MB | 7 s |
| rpi4 | 66 MB | 9 s |
| vps | 7 MB | 9 s |

`raw-data` mode walks every tree of every snapshot to find the blobs they reference. The cost follows the number of files and directories, and the Beelink backs up Gitea, whose repositories are many small files. The same tree made a recursive `ls` take 92 s in BACKUP-055. With `--no-cache`, which the read-only watcher needs, each run downloads every tree again.

**Solution**: `stats` got its own `STATS_TIMEOUT` (600 s), and the probe logs `stats took Ns` on every run. The Job's deadline and grace period are derived from the probe's calls. The test counts the `restic_read` calls in `probe.sh` rather than hardcoding them; the hardcoded 2 had already been stale since a third call was added, with the worst case (720 s) past the 600 s deadline and the test green. A failed `stats` never marks a node unhealthy, and it makes the fleet sum `null` rather than smaller.

**Rule**: Budget a restic command by what it walks, not by the repository's size in bytes: `stats --mode raw-data`, `ls` and `check --read-data` scale with tree count, pack count and bytes respectively. Measure the slowest node before sharing a timeout between calls, and log the duration so the headroom is visible before it runs out.

**Tags**: `#restic` `#r2` `#backup-057` `#issue-1920`
