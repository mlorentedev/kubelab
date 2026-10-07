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
- The Beelink stores 1.8x what `raw-data` reported: the unreferenced packs, index and snapshot files the old measure left out, and R2 bills. The fleet is 0.70 GB of the 10 GB free tier.
- Each listing took 0-1 s against 31-601 s for `stats` on the same repositories. A listing's cost follows the object count, not the snapshot count.

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 (four numeric node sizes and a numeric fleet, staging and prod) -> staging run above; prod run after merge
- [ ] AC2 (fleet = bucket roots, each once) -> `test_each_node_reports_its_prefix_and_the_fleet_its_buckets`, `test_it_sizes_each_bucket_once_and_each_node_prefix`
- [ ] AC3 (time does not follow snapshots) -> baseline and staging tables above; `test_each_node_logs_how_long_its_listing_took`
- [ ] AC4 (failures are null, never unhealthy, sizing exits 0) -> `test_an_unmeasured_bucket_makes_the_fleet_size_null`, `test_a_failed_node_listing_is_null_and_never_fails_the_pod`, `test_a_hung_listing_is_cut_off_and_null`, `test_without_a_sizes_file_every_size_is_null_and_named`
- [ ] AC5 (no `raw_bytes` reader left) -> `test_no_watcher_emitter_or_reader_still_says_raw_bytes`, `test_the_size_rule_fires_at_eighty_percent_of_the_free_tier_declared_in_common`

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

-
-

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
