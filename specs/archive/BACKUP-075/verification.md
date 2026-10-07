---
tags: [spec, verification, templates]
created: "2026-10-06"
---

# Verification - BACKUP-075

## Baseline: `restic stats --mode raw-data` in prod (before)

Read from Loki on 2026-10-07 (`toolkit obs logs --env prod`, the watcher's `stats took` lines, last 7 days):

| Node | 2026-10-04 12:10 | 2026-10-07 01:15 | Last size (raw_bytes) |
|---|---|---|---|
| beelink | 600 s (killed) | 601 s (killed) | 142 747 230 (2026-10-04 00:07, last success) |
| rpi3 | 17 s | 31 s | 151 630 989 |
| rpi4 | 19 s | 35 s | 170 033 395 |
| vps | 19 s | 36 s | 77 948 912 |

Every node's `stats` roughly doubled in three days while its repository stayed in the 80-170 MB range: the cost follows the snapshot count (hourly ships), not the bytes (lesson-490). The Beelink only crossed the timeout first. Raising `STATS_TIMEOUT` would buy days, not a fix. The fleet is about 0.55 GB of the 10 GB free tier, so the alert has been firing on no data, not on size.

## After: object listing in staging

`make watcher-run NAME=r2-backup-watcher ENV=staging` on 2026-10-07 04:06Z, with staging's Argo CD app pointed at `feat/backup-075-r2-bucket-size` (`make argo-set-revision`). The staging watcher reads the same four R2 repositories as prod (one `targets.txt` in the base), with the same read-only token. The Job succeeded in **36 s**, all four nodes `healthy:1`.

| Node | `stored_bytes` (listing) | Listing took | Last `raw_bytes` (`stats`) |
|---|---|---|---|
| beelink | 256 097 048 | 1 s | 142 747 230 (2026-10-04) |
| rpi3 | 161 660 767 | 0 s | 151 630 989 |
| rpi4 | 197 792 899 | 1 s | 170 033 395 |
| vps | 84 141 753 | 0 s | 77 948 912 |
| **bucket `kubelab-backups`** | **699 692 467** | 0 s | (no bucket figure existed) |

- The read-only token lists the bucket root: R2 tokens are scoped to buckets, not prefixes. The gate in `tasks.md` passed.
- The bucket root equals the sum of the four prefixes to the byte: today nothing in the bucket lies outside a node's repository.
- The Beelink's listing reads 1.8x its last `raw-data` figure. The two were taken three days apart (`stats` last succeeded on 2026-10-04), so growth and the unreferenced packs, index and snapshot files the old measure left out both contribute, and this run does not separate them. The fleet is 0.70 GB of the 10 GB free tier.
- Each listing took 0-1 s against 31-601 s for `stats` on the same repositories. A listing's cost follows the object count, not the snapshot count.

## After: prod (#2081 merged as bb0e0e86)

`make watcher-run NAME=r2-backup-watcher ENV=prod` on 2026-10-07 06:07Z: Job **52 s**, all four nodes `healthy:1`, every listing 0-1 s.

| Node | `stored_bytes` |
|---|---|
| beelink | 258 840 369 |
| rpi3 | 166 632 291 |
| rpi4 | 210 715 285 |
| vps | 84 141 753 |
| **fleet (bucket `kubelab-backups`)** | **720 329 698** |

After this run, `make alerts` showed nothing firing: the free-tier alert had fired since 2026-10-06 00:19Z, and both it and the shrink alert resolved. The run came about 43 minutes after the merge, not right after the sync as planned. In that gap the shrink rule paged on no data, which PR-Agent's second pass had predicted: the rename's window is real and measured, not theoretical.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 (four numeric node sizes and a numeric fleet, staging and prod) -> staging run 04:06Z and prod runs 06:07Z/06:10Z above (`features.json` f1: 5 numeric lines)
- [x] AC2 (fleet = bucket roots, each once) -> `test_each_node_reports_its_prefix_and_the_fleet_its_buckets`, `test_it_sizes_each_bucket_once_and_each_node_prefix`
- [x] AC3, in substance only (listing is 0-1 s against 31-601 s for `stats`; not shown independent of snapshot count, nor measured both ways in one sitting, see Known gaps) -> baseline and staging tables above; `test_each_node_logs_how_long_its_listing_took`
- [x] AC4 (failures are null, never unhealthy, sizing exits 0) -> `test_an_unmeasured_bucket_makes_the_fleet_size_null`, `test_a_failed_node_listing_is_null_and_never_fails_the_pod`, `test_a_hung_listing_is_cut_off_and_null`, `test_without_a_sizes_file_every_size_is_null_and_named`
- [x] AC5 (no `raw_bytes` reader left) -> `test_no_watcher_emitter_or_reader_still_says_raw_bytes`, `test_the_size_rule_fires_at_eighty_percent_of_the_free_tier_declared_in_common`

## Test status

- Test suite: `make test-fast` -> 3855 passed, 16 skipped, 2 xfailed (rebased branch, 2026-10-07)
- Manual smoke test: `make watcher-run` in staging (04:06Z) and prod (06:07Z, 06:10Z); listing timings and sizes above
- No regressions in existing test suite: yes

## Known gaps (adversarial review, 2026-10-07)

- **AC3 holds in substance, not in its strict form.** The `stats` baseline (Loki) and the listing timings were taken hours apart, not on the same repository in one sitting, and the Beelink was never sized both ways because `stats` was already killed there. A listing's cost follows the object count, and objects grow with snapshots, though far more slowly than a tree walk: the claim is "orders of magnitude cheaper", 0-1 s against 31-601 s, not "independent of history". `size.sh` does not record rclone's object `count`, so headroom is judged by the logged duration.
- **The init container's memory is unmeasured.** `--fast-list` holds the bucket's listing in memory under a 128Mi limit. An OOM ends the pod before the probe, and the health rule pages on no data after its 24 h window (documented in the manifest). Today's bucket lists in under 1 s.
- **Buckets are deduplicated by name, not by host and name.** That only matters if two endpoints ever share a bucket name; there is one endpoint today.
- **Two-bucket fleets** were untested at merge. Added after review (854d5382): `test_the_fleet_sums_every_bucket_once`, `test_either_unmeasured_bucket_makes_a_two_bucket_fleet_null`, `test_two_buckets_are_each_listed_once_at_their_root`. Each turned red under its mutation: the fleet taking the last bucket instead of the sum, a null bucket skipped instead of nulling the fleet, and the bucket dedup removed.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- rclone over a connection-string remote, no config file: the endpoint comes from each target's repository URL, so `targets.txt` stays the only source of where the repositories live.
- The bucket is listed at its root and counted once, because R2 bills every object and a read-only bucket-scoped token can list the root (checked in staging).
- `size.sh` always exits 0. A failure of the container itself (image pull, OOM) still ends the pod before the probe; the health rule then pages on no data after its 24 h window. Documented in the manifest rather than engineered away.
- The field was renamed `raw_bytes` -> `stored_bytes` because it now means a different quantity. The cost is one no-data window at deploy, closed by a manual `watcher-run`.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/storage-backup/lesson-524-size-a-backup-bucket-by-listing-it-not-by-walking-its-snapshots.md
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: a change of measurement inside an existing component; the spec records the decision and the rejected alternative
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: one project so far; the lesson's rule is the candidate if it recurs

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-075/` -> `specs/archive/BACKUP-075/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
