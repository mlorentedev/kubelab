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

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`

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

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-075/` -> `specs/archive/BACKUP-075/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
