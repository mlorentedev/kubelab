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

## Scratch steps 2, 2b and 3

2026-10-02, against `kubelab-backup-scratch` with the repository at the bucket root, so `data/`, `snapshots/`, `keys/` and `config` sit under the lock rules. A first `init` under a `measure/` prefix put the repository outside every rule; it was deleted and re-initialised at the root before any step was recorded. Credentials were a scratch Object Read & Write token, read from SOPS into the child process only.

**Step 2 passes.** Two `backup`s of different data saved `715f817d` and `cb2bde94`, and `check` reported `no errors were found`. Each `backup` removed its own lock file: `locks/` held 0 objects afterwards, so `locks/` is outside the rule as intended. The exit codes of these three calls were not captured (the wrapper read `PIPESTATUS` in zsh). The saved snapshots and the later `check` (rc 0, below) are the evidence.

**Step 2b passes.** A third `backup` changed a subset of the second's files (`eac4003f`, rc 0, 6 packs). `forget cb2bde94 --prune --dry-run` without `--max-repack-size 0` planned `to repack: 14 blobs / 11.446 MiB`. With the flag it planned `to repack: 0 blobs / 0 B`. Both rc 0. The flag is what stops a rewrite, which is the only path that makes a pack younger than its snapshots.

**Step 3 passes on the fleet's restic, and the version matters.** `forget 715f817d` is the first snapshot, younger than R. R2 refused the snapshot file's DELETE:

```
Remove(<snapshot/715f817d4c>) returned error, retrying after ...: client.RemoveObject: The object is locked by the bucket policy.
Remove(<snapshot/715f817d4c>) failed: client.RemoveObject: The object is locked by the bucket policy.
unable to remove snapshot/715f817d4cee9517b3ed3bd08a3fcc696469a46ee4af33de4b5c8993dc34eed1 from the repository
failed to remove one or more snapshots
```

This is R2's lock refusal, not a restic-side error, so no `restic unlock` was needed.

- **restic 0.19.1** (`backup.r2.restic_version`, what every node runs; run in `restic/restic:0.19.1`), in the ship's form `forget <id> --prune --max-repack-size 0`: **rc 3** after 14:29 of retries, and the prune never ran. This is the exit code Q6's prune signal keys on.
- **restic 0.18.1** (the workstation's), plain `forget <id>`: the same refusal and the same 14:43 of retries, but **rc 0**. The following `prune --max-repack-size 0` found nothing to delete (rc 0). Any measurement of this path has to run the pinned version. On 0.18.1 a refused forget reads as success.

Afterwards `restic snapshots` still listed all three snapshots, `715f817d` included. `repair index` returned rc 0, and `check` returned `no errors were found`, rc 0.

**Measured for PR 4: a refused DELETE costs about 14.5 minutes, not an instant error.** restic retries each refused object with backoff, about 13 retries over 14:29 on 0.19.1, before giving up. This was measured for one snapshot file. Whether k refused objects cost k times that, or run concurrently, is not measured. Size the ship's prune step for this. `node-backup-ship.service.j2:44` sets `TimeoutStartSec=600`, which is shorter than one refused DELETE. On the current unit, systemd would kill the ship mid-retry with `Result=timeout`, after a successful `backup`. The ship would fail as a whole, which is the outcome Q6 rules out, and the prune-failure line would never be written. PR 4 has to bound the prune itself, below the unit's timeout, and report the bound being hit as a prune failure (tasks.md, the Q6 task).

**Step 3b: R2 refuses the pack DELETE, and restic exits 0.** A 0.19.1 `backup` of 300 MiB was killed after it had written three packs (6 to 9 under `data/`) and before any snapshot. The kill left a restic lock behind, so the first `prune` stopped on it with rc 11 (`repository is already locked`), a restic-side error. A plain `unlock` did not remove a 20-second-old lock from another host. After `unlock --remove-all`, `prune --max-repack-size 0` planned `to delete: 0 blobs / 48.773 MiB` (the three unreferenced packs) and then:

```
deleting unreferenced packs
Remove(<data/4de1b7dfaa>) failed: client.RemoveObject: The object is locked by the bucket policy.
unable to remove data/4de1b7dfaa7f2fb21e1509a17cec8be3059acbcc46e0cf8a422856a0f0179d36 from the repository
(the same two lines for data/12fd9c4d6f... and data/6febda4f54...)
[14:53] 0.00%  0 / 3 files deleted
done
```

**rc 0**, after 58 retries over 14:53. The three packs ran their retries concurrently, so three refused objects cost about what one did. Afterwards there were still 9 packs and 3 snapshots, and `check` reported `no errors were found`, rc 0.

What this changes for Q6: restic reports the two refusals differently. A refused **snapshot** DELETE (step 3) exits 3. A refused **pack** DELETE (step 3b) exits 0. The pack case is the one the proposal expects on every on-demand node: a node powered off mid-run leaves unreferenced packs, and each `prune` within R of that will hit them. A prune signal keyed on restic's exit code would stay silent for this case. Nothing would fail, but every nightly prune would take about 15 minutes until the packs age past R. Under today's `TimeoutStartSec=600`, systemd would kill the ship instead. The only output that distinguishes the case is the text: `unable to remove ... from the repository` and `The object is locked by the bucket policy`. PR 4 has to read that text, not only the exit code. How it does so is a design decision for the operator, recorded in `tasks.md` with the Q6 task.

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
