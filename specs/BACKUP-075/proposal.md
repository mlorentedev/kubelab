---
id: "BACKUP-075"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-10-06"
issue: "mlorentedev/kubelab#2077"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "Backup is the operator's top priority (2026-10-04) and the R2 free-tier alert has been firing on no data since 2026-10-06; the operator chose the override on 2026-10-07. (24 active, limit 10, 2026-10-06)"
---

# BACKUP-075

> **Naming**: file lives at `<repo>/specs/BACKUP-075/proposal.md`. `BACKUP-075` is `AREA-NNN-slug` (e.g. `TOOL-001-secret-drift`).

## Why

<!-- from issue #2077: BACKUP-075: the R2 watcher cannot size the Beelink repository, so the free-tier alert fires on no data -->

The free-tier alert has been firing since 2026-10-06 00:19 UTC on no data, not on size. The watcher sizes each repository with `restic stats --mode raw-data`, which walks every snapshot's tree (lesson-490). On the Beelink that grew from 290 s to 429 s and then past the 600 s `STATS_TIMEOUT` (since 2026-10-04 06:10), and one null size makes the fleet sum null. So the operator cannot tell "near the bill" from "unmeasured", which is how an alert gets ignored. It also measures the wrong quantity: R2 bills every stored object, and `raw-data` counts referenced blobs only. Unreferenced packs, index and snapshot files, and objects a lock refused to delete all remain in the bucket and are billed, and none of them is in `raw-data`.

## What

- The watcher measures what R2 stores by listing objects (S3 ListObjectsV2) with `rclone size --json`, not by walking snapshots. The measurement's cost is bounded by the number of objects, not the number of snapshots.
- Each `r2_backup_node` line carries `stored_bytes`: the bytes under that node's repository (bucket + prefix). The shrink rule reads it.
- The `r2_backup_health` fleet line carries `stored_bytes`: the sum of the **whole buckets** the watcher's targets name, each bucket counted once. That is the quantity R2 bills, including anything outside a node prefix. The free-tier rule reads it, and it stays null when any bucket is unmeasured, as today.
- The field `raw_bytes` is renamed `stored_bytes` everywhere it is emitted or read (operator, 2026-10-07), because the value is no longer restic's raw data.

## Out of scope

- Moving any node to its BACKUP-057 bucket (BACKUP-057 PR 4). This spec makes the measurement per bucket, so PR 4 changes the targets, not the measurement.
- Changing the alert thresholds or the 80% free-tier level.
- Pruning, repacking or any other change to what the nodes store.

## Risks / open questions

- **Client (decided, operator 2026-10-07): `rclone`.** restic 0.19.1 has nothing that lists objects with sizes (`stats` offers four modes, all tree walks; `list packs` prints IDs only; checked 2026-10-07). rclone runs as an init container (`r2-size`, script `size.sh`) with no config file: the remote is an on-the-fly connection string (`:s3,provider=Cloudflare,env_auth=true,no_check_bucket=true,endpoint=...`) whose endpoint comes from each target's repository URL, and the credential is the same `AWS_*` read-only pair. It writes one `<kind> <name> <bytes|null> <seconds>` line per bucket and per node to an emptyDir, and the probe reads it. Its image is pinned in `common.yaml` beside the restic one. Rejected: Cloudflare analytics GraphQL (a new token in the cluster, and its numbers lag).
- **Rename cost.** Renaming empties both `unwrap` windows until the first run after deploy, and both rules alert on no data. Mitigation: `make watcher-run NAME=r2-backup-watcher ENV=<env>` right after each environment's deploy.
- **Read-only token and listing.** The token must allow ListObjectsV2 on the bucket root, not only under a node prefix; restic's `snapshots/` listing already proves prefix listing, not root listing. Measured in the first task. rclone must not try to create or check the bucket (`--s3-no-check-bucket`).
- **The overlap during BACKUP-057 PR 4.** The node-bucket token BACKUP-057 mints is refused on `kubelab-backups`, so after a node moves the watcher sees the old copy only while it still holds the old read-only pair. That blind spot is already bounded by BACKUP-057's gate (alert headroom larger than the frozen old copy, `specs/BACKUP-057/tasks.md`); this spec does not widen any token.
- **The shrink rule sees prunes.** `stored_bytes` falls when the daily prune deletes packs, which `raw-data` partly hid. With 30-day retention and daily prunes the drop per 6 h is small against the rule's 50% threshold; recorded, not changed.
- **Cost.** One Class A ListObjectsV2 per 1 000 objects per bucket or prefix per run, four runs a day, well inside the free million a month.

## Acceptance criteria

- [ ] **AC1**: Every watcher run logs a numeric `stored_bytes` for all four nodes and for the fleet line, in staging and prod (`make watcher-run`).
- [ ] **AC2**: The fleet `stored_bytes` is the sum of each named bucket's root size, each bucket once; a test with two nodes in one bucket and an object outside any prefix proves the bucket is counted once and the stray object is counted.
- [ ] **AC3**: Measurement time does not grow with snapshot count: one repository is sized both ways (rclone and `stats --mode raw-data`) and both are timed, with the gap recorded in `verification.md`, and the per-node timing line stays in the probe's log.
- [ ] **AC4**: A listing that fails gives the entry it measures `stored_bytes: null` (a node prefix: that node; a bucket: the fleet line), a fleet whose buckets were not all measured is `null`, and no size ever changes `healthy`. The sizing step always exits 0, so a failed listing can never stop the health probe from running. The tests run both scripts with fake clients, no R2 in CI.
- [ ] **AC5**: No consumer still reads `raw_bytes`: the Grafana rules, the runbook and the tests read `stored_bytes`, and a test fails if `raw_bytes` reappears in the watcher's emitters or readers.

## References

- Bitácora board: the GitHub issue / Project item tracking this spec (see the `issue:` frontmatter field)
- Related spec: `specs/BACKUP-057/` (per-node buckets, Q3 retention, the overlap gate)
- Lessons: lesson-490 (stats cost scales with trees), lesson-511 (refused deletes)
