---
tags: [spec, verification, templates]
created: "2026-09-30"
---

# Verification - BACKUP-057

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] Criterion 1 -> commit `<hash>` / test `<name>`
- [ ] Criterion 2 -> commit `<hash>` / test `<name>`
- [ ] Criterion 3 -> commit `<hash>` / test `<name>`
- [ ] Criterion 4 -> commit `<hash>` / test `<name>`
- [ ] Criterion 5 -> commit `<hash>` / test `<name>`

## PR 1 gate: size against the free tier (Q3)

Measured 2026-09-30 23:41Z by `make watcher-run NAME=r2-backup-watcher ENV=staging`, with staging's Argo CD app pointed at `feat/backup-057-watcher-size`. The staging watcher reads the same four R2 repositories as prod (one `targets.txt` in the base), so these are the prod repositories' sizes. The prod run follows the merge.

| Node | `raw_bytes` | `stats` took |
|---|---:|---:|
| beelink | 61,190,162 | 143 s |
| rpi3 | 52,615,356 | 7 s |
| rpi4 | 65,879,867 | 9 s |
| vps | 7,128,999 | 9 s |
| **fleet** | **186,814,384** | Job 193 s |

Projection for `--keep-within 31d`, as an upper bound that assumes no deduplication at all (every daily snapshot new data): 32 × 186.8 MB = 5.98 GB for the new buckets. Add the old copy, which `kubelab-backups` keeps until Q2 deletes it: 0.19 GB. That makes 6.17 GB, under the 8 GB alert (80%) and the 10 GB free tier. **Gate: passes.** Four numeric sizes, and the bound fits with both copies stored. R = 30 stands. The alert's blind spot during the overlap is the old copy, which the watcher no longer sums once a node migrates: 0.19 GB, against 2 GB of headroom between the 8 GB alert and the 10 GB free tier, so a fleet that crosses the free tier unseen would have to grow past the alert first.

The first run returned `null` for the Beelink: `stats --mode raw-data` walks every tree, and its Gitea tree outran the 60 s `RESTIC_TIMEOUT` ("signal terminated received", Loki). That is the tolerated failure working as designed; the fleet sum was `null` and the gate would have stopped. `stats` now has its own `STATS_TIMEOUT` (600 s, about 4× the measurement), and the deadline and grace period are derived from the probe's calls.

## PR 2 gate: the token that manages the locks (scratch step 1)

2026-10-02. `make tf-r2-apply SCRATCH=1` with the SOPS DNS token `cloudflare.api_token` was refused before any lock call: `POST /accounts/<id>/r2/buckets` returned **403**, code 10000 "Authentication error". A plan had shown nothing, as tasks.md predicted: planning a resource that does not exist yet makes no R2 call.

The operator minted a separate user API token, `Account · Workers R2 Storage · Edit` on this account only, stored as `cloudflare.r2_admin_token` in `common.enc.yaml` and registered in `SECRET_CATALOG` (`envs=("prod",)`, `Expiry.PROVIDER`, checked by `cloudflare_token_expiry`; `toolkit secrets check-expiry` reads it as valid, no expiry set). `tf-r2-plan` / `tf-r2-apply` read that key, never the DNS token, so the token that can lift a lock reaches nothing that only needs DNS. Commit `e529a5c1`.

The same apply with it returned rc 0: `cloudflare_r2_bucket.scratch` and `cloudflare_r2_bucket_lock.scratch` created (the four rules, `data/`, `snapshots/`, `keys/`, `config`, each `Age` 86400 s). **Step 1 passes**, which also shows the API accepts a one-day retention.

The admin token sits in a file every SOPS recipient decrypts, so #1852 (SEC-022) gates this spec's archive (proposal item 1).

## Test status

- Test suite: `<command> -> <output / coverage %>`
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- `raw-data` was kept over summing blob lengths from the index files, which would be bounded by index size rather than tree size. At 143 s the Beelink fits a dedicated timeout, and the spec's method needed no amendment. Revisit if `stats took` passes half of `STATS_TIMEOUT`: the probe logs the figure on every run.
- The Job deadline assumed 2 restic calls per node; the probe has made 3 since BACKUP-058, so the worst case (720 s) already exceeded the 600 s deadline while the test passed. The test now counts the calls in `probe.sh`.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [ ] Lesson for the repo's `docs/lessons/`? <yes: path / no: reason>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes: path / no: reason>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes: path / no: reason>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-057/` -> `specs/archive/BACKUP-057/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
