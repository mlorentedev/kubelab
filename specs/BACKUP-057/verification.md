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

**Step 4 passes.** At 04:38Z, a direct `aws s3api delete-object` of `data/12/121edff0...1161` (from the first two snapshots, written at 03:18Z) was made with the scratch Object Read & Write token, the credential class each node will hold. It returned `An error occurred (ObjectLockedByBucketPolicy) when calling the DeleteObject operation: The object is locked by the bucket policy.` with rc 254. `head-object` afterwards still returned the object (12001156 bytes). A node's own credential cannot delete its young backups, which is the half of AC3 the scratch bucket can show. The prod-bucket repeat stays with the prod task.

**Two inputs for the Q6 decision, measured on 0.19.1.**

- **The nightly form does not prune when `forget` selects nothing.** `forget --keep-within 31d --prune --dry-run --max-repack-size 0`, with every snapshot younger than 31 days, kept all three snapshots and printed no prune phase at all (rc 0). The three orphan packs from step 3b were not planned. A ship only reaches the refused pack DELETEs on a night when `forget` removes a snapshot. In prod that means a night when a snapshot crosses 31 days, while an orphan pack younger than R exists.
- **restic has no knob that shortens the retries.** `restic --help` offers `--retry-lock` (repository locks) and `--stuck-request-timeout` (stalled requests). `restic options` lists `s3.retries`. `forget 715f817d -o s3.retries=0` still took 14:48 (894 s, 22 retry lines printed) and exited 3. The backoff comes from restic's own retry layer (`Remove(...) returned error, retrying after`), not from the S3 client. Any bound on a refused prune has to come from outside restic: a `timeout` around the step, or the prune in a unit of its own.

**Step 5 is not before 2026-10-03T05:00Z.** The last write to a locked prefix was step 3b's packs, at about 04:18:45Z. Every later step either wrote nothing under the rules or was refused. R is one day, so 05:00Z on 2026-10-03 leaves a margin over the last write.

## Scratch step 5

2026-10-03 at 22:07Z, about 42 hours after the last write. The wrapper and credentials were the same as in steps 2-4. Before the step, `restic snapshots` listed all three snapshots, `715f817d` among them, with 9 packs under `data/` and no repository locks.

**Step 5 passes.** This is the measurement showing that the schedule can prune under the lock.

| Call | rc | Retries | Output |
|---|---|---|---|
| `forget 715f817d` | 0 | 0 | `1 / 1 files deleted` (22:08:03Z) |
| `prune --max-repack-size 0` | 0 | 0 | `to delete: 13 blobs / 60.219 MiB`; `deleting unreferenced packs 3 / 3`; `removing 2 old packs 2 / 2`; `done`; 7 s (22:08:10Z to 22:08:17Z) |

The prune log has no `locked` or `retrying` line. Afterwards:

- `restic snapshots` lists 2 snapshots, `cb2bde94` and `eac4003f`.
- The pack count under `data/` dropped from 9 to 4.
- `check` reports `no errors were found`, rc 0.

Among the deletions are the three orphan packs that step 3b's interrupted `backup` left behind. They were refused at step 3b, because they were younger than R. Here they are older and their DELETE was accepted. A node's unreferenced packs therefore clear themselves once they age past R, with nobody acting on them.

## Scratch step 6

2026-10-03, right after step 5. These are the steps the teardown took.

1. **Empty the bucket.** Terraform cannot destroy a bucket that still holds objects. `aws s3 rm s3://kubelab-backup-scratch --recursive` used the scratch Object Read & Write token and returned rc 0. It deleted all 9 objects, and a listing afterwards found 0. The locked prefixes were deleted with the rest: every object in them was older than R, the same reason step 5's DELETEs were accepted.
2. **Remove the lock, then the bucket, through Make.** The command is `make tf-r2-apply SCRATCH=1 SCRATCH_DESTROY=1`. `SCRATCH_DESTROY` keeps the scratch `-target`s and turns `scratch` off (commit `78a54879`). On its own it is refused: without the targets, an apply with `scratch` off would also create every node bucket.
   - The plan read `0 to add, 0 to change, 2 to destroy`.
   - The apply ran from 22:13:43Z to 22:13:49Z and returned rc 0. Terraform destroyed `cloudflare_r2_bucket_lock.scratch[0]` before `cloudflare_r2_bucket.scratch[0]`.
   - `terraform state list` is now empty.
   - A listing of the bucket returns `NoSuchBucket`.
3. **Delete the three scratch keys from `common.enc.yaml`.** They had never been committed, and the uncommitted diff held only them plus SOPS's own metadata. Restoring the committed file therefore removed exactly those three keys, with no re-encryption. `toolkit secrets show` now exits 1 for each of them, and still exits 0 for `cloudflare.r2_admin_token`.

The scratch Object Read & Write token itself still exists in Cloudflare. The bucket it reached is gone, so it can read or write nothing. The operator revokes it in the dashboard (R2, then *Manage API tokens*), because no IaC manages it.

**AC3's scratch measurement is complete.** The prod-bucket repeat of step 4 stays with the prod task.

## AC2: the node buckets

2026-10-03, from the main checkout, which holds the R2 state (operator decision: same home as the DNS root's).

- The first `make tf-r2-plan` read `8 to add, 0 to change, 0 to destroy`: four buckets and four lock rules.
- `make tf-r2-apply` created `kubelab-backup-{beelink,rpi3,rpi4,vps}` and their locks, returning `8 added, 0 changed, 0 destroyed`.
- **The second plan was not clean.** It read `0 to add, 4 to change`, and the change was a reorder only. The API returns a bucket's lock rules sorted by `id`. The HCL listed them in the order `LOCKED_PREFIXES` renders them (`data/`, `snapshots/`, `keys/`, `config`). Every plan would have shown the same diff, so AC2's "no diff" could never hold. The scratch measurement never ran a second plan, which is why it did not see this.
- Fix: `lock_rules` now iterates a map keyed by the rule id, so Terraform emits it in id order. Planned against the live state with the fix applied, the result is `No changes. Your infrastructure matches the configuration.` `test_the_lock_rules_are_ordered_by_id_as_the_api_returns_them` pins the shape.
- The fix merged as #2055 (`a1a7f300`). `make tf-r2-plan` run from the main checkout on master reads `No changes. Your infrastructure matches the configuration.`

## PR 3: the per-node credentials, minted

2026-10-03. The operator settled the open items:

- **Minting token.** `cloudflare.r2_token_minter` is an account token holding only *Account API Tokens: Edit*, with a 30-day TTL. `cloudflare.r2_admin_token` was not widened.
  - Before it existed, a read-only probe with `r2_admin_token` against `GET /accounts/{id}/tokens/permission_groups` got **HTTP 403**. The new token gets 200.
  - Cloudflare's *user* verify endpoint answers **401** for an account token. Its expiry is read from `/accounts/{id}/tokens/verify` (`cloudflare_account_token_expiry`), which reports 2026-11-03.
- **Where the keys live.** Each node's write pair goes to `prod.enc.yaml`, audited under prod. The restic passwords and the watcher pair go to `common.enc.yaml`, audited under staging and prod, because the staging watcher reads them. `sops_file_for` decides the file, and a test ties that choice to each key's audit envs.
- **Watcher pair.** It lives at `backup.r2.watcher.{access_key_id,secret_access_key}`, in one token naming the four node buckets. Cloudflare's token policy takes a map of resources, so proposal item 4 needed no fallback.

`make backup-mint-node-tokens ENV=prod` returned rc 0. All five tokens passed the by-consequence check before anything was stored:

- each node token listed its own bucket and got `AccessDenied` on another node's;
- the watcher token listed all four node buckets and got `AccessDenied` on `kubelab-backups`.

The two SOPS files were decrypted before and after the mint and compared by path, never by value:

- `prod.enc.yaml`: added 8 (`backup.r2.nodes.<node>.{access_key_id,secret_access_key}`), removed 0, changed 0.
- `common.enc.yaml`: added 6 (four `backup.nodes.<node>.restic_password` and the watcher pair), removed 0, changed 0.
- Both files kept the same two age recipients.

The writer re-encrypts the whole file, so the git diff spans every line. That is filed as #2056 (TOOL-099).

`make secrets-audit ENV=prod` and `make secrets-audit ENV=staging` both returned rc 0.

**Escrow.** The four new restic passwords were copied into Bitwarden on 2026-10-03 with `dotf`, the same way as `backup.restic_password`. Each Bitwarden entry was compared with its SOPS value by hash, never printed: 5/5 matched.

## PR 4a: the prune in its own unit (Q6, amended)

2026-10-03/04, on beelink (prod node, restic 0.19.1, systemd 255; rpi3 runs 257, vps and rpi4 255).

- Deploy: `make backup ENV=prod NODE=beelink CHECK=1` ok (the one ignored task is the timer start, whose unit file `--check` never wrote). Real run `changed=7`, re-run `changed=0`. After the stale-lock fix: `changed=1` (the ship script), re-run `changed=0`.
- `make backup-schedule NODE=beelink ENV=prod` lists `node-backup-prune.timer` (next run Mon 2026-10-05 00:03) and reports `failures in the last 7 days: 0`.
- `make backup-node NODE=beelink ENV=prod PRUNE=1`: `Result=success`, rc 0, 4 s. A ship that follows logs no `forget` and no policy line.
- **Ship queued during a prune.** systemd reports the ship as `start waiting`, and it starts only after the prune exits (06:27:14 prune exit, 06:27:16 ship start). Both succeed. This is the `After=` ordering.
- **Prune started during a ship's `backup`.** restic logs `repo already locked, waiting up to 10m0s for the lock`. Ship 06:28:50 to 06:29:00 and prune 06:28:55 to 06:29:04, both succeed. This is `--retry-lock`.
- **Prune killed while it held its lock.** The first attempt killed `forget` before it had locked, so it proved nothing. The test was repeated with `SIGSTOP` in steps until `restic list locks --no-lock` reported the lock, then `SIGKILL`: the unit ended `Result=signal`, and one exclusive lock remained in R2.
  - **Defect found.** The next ship failed with exit 11 (`repository is already locked exclusively by PID 187939`). The reachability probe, `restic snapshots`, takes a lock, and it runs before `unlock`. So a killed prune would have failed every ship until someone intervened.
  - **Fix.** The probe and `cat config` run with `--no-lock`; both only read. A fake-restic test that models a stale exclusive lock was red before the fix, and removing either `--no-lock` or the `unlock` turns it red again (lesson-521).
  - **After the fix**, against that same real lock, the ship logged `successfully removed 1 locks` and then `snapshot 627fad41 saved`.
- **Prune facing a stale exclusive lock.** A lock was left by hand, outside systemd so nothing paged, by killing a `forget` once it held its lock. `PRUNE=1` then logged `successfully removed 1 locks`, applied the policy (20 snapshots kept) and finished.
- Three `OnFailure` notifications fired during these tests: two from the killed prunes (`signal`) and one from the ship that failed before the fix. Each `kubelab-notify@<unit>.service` ran and exited 0 (journal, 06:29:21, 06:32:15, 06:32:24).
- `make backup-schedule NODE=beelink ENV=prod` then reported `node-backup-prune.service failures in the last 7 days: 2`. Those are the two deliberate kills of 2026-10-04, not faults: AC3's seven-day window must start after them.
- After review (#2066), the report tells a clean week from a node without the unit. `make backup-schedule NODE=all ENV=prod` printed `failures in the last 7 days: 2` on beelink and `is not installed on this node (not-found): nothing measured` on kubelab-vps, rpi3 and rpi4, which do not have the role yet.
- **Rollout after #2066 merged (2026-10-04).** `make backup ENV=prod CHECK=1` reported 6 changes on each of kubelab-vps, rpi3 and rpi4; its one ignored error is the timer start. The real run gave `changed=7` on those three and `changed=0` on beelink, and a re-run gave `changed=0` on all four. `make backup-node NODE=all ENV=prod PRUNE=1`, then the ship, each returned rc 0 on all four nodes. `make backup-schedule NODE=all ENV=prod` lists `node-backup-prune.timer` armed on all four (next run 2026-10-05 around 00:01-00:04 local) and reports 0 prune failures on the three new nodes (2 on beelink, from the kill tests).
- `--no-lock` keeps the probe's exit codes: `restic snapshots -q --no-lock` exits **10** on a prefix with no repository and **0** on beelink's, so the first-ship `init` path is unchanged.

## PR 4c: the isolation probe, before the migration

2026-10-07, `make backup-isolation-probe ENV=prod` from the branch, with `own_bucket_nodes: []` and the four node buckets empty. Exit 1, as designed. Its eight failure lines were exactly the expected ones: four for nodes not declared, and four for buckets with nothing under `data/`. No cross-node request produced a failure line. So R2 refused all 24 cross requests (4 x 3 ordered pairs, list and delete, each with the minted node pairs) with `AccessDenied`. That is the scope half of AC3, measured live. The lock half waits for the sitting, because there is no pack yet for the lock to refuse a delete of.

Seven mutations of `backup_isolation.py`. Six each turned a test red: accepting any refusal reason (cross), accepting any refusal reason (own), not failing on an empty prefix, taking the oldest pack instead of the youngest, deleting a real key across nodes, and skipping the declaration check. The seventh, dropping the `rc == 0` branches, is equivalent: an accepted request still fails as "not refused for the right reason".

After the first PR-Agent pass the own delete moved behind two guards, so it is attempted only where it can only be refused. The bucket's lock rules are read with the admin token and must hold `data/` by age for at least R, and the youngest pack must be more than a day inside R. Re-run live on 2026-10-07: still `24 of 24 cross-node requests refused with AccessDenied`. The lock read passed on all four buckets, since each reached its listing and failed only on the empty `data/`. Eight more mutations, each red: the guard not skipping the delete, `enabled` ignored, R ignored, an API failure tolerated, no safety margin, no age check, and picking the youngest by string instead of by instant. A type check on `Age` was dropped as redundant, because only an `Age` condition carries `maxAgeSeconds`.

## The migration sitting (AC4)

2026-10-08, 01:55Z to 02:25Z, one sitting, `make backup-migrate NODE=<n> ENV=prod` from `chore/backup-057-own-buckets`, which stacks on #2121.

The first vps run failed at the copy and changed nothing. `restic copy` locks the source too, and the temporary token is read-only on `kubelab-backups`. The step stopped before the declaration, and the token was revoked. The fix is #2121 (`--no-lock` on the copy) and lesson-538. The re-run reused the `config` and `keys` that the first `init` had written.

| Node | Source snapshots (dry run) | Matched copies, one each | Repository pinned |
|---|---|---|---|
| vps | 39 | 39 | `e5870490…` |
| rpi3 | 40 | 40 | see `common.yaml` |
| rpi4 | 52 | 52 | see `common.yaml` |
| beelink | 61 | 61 | see `common.yaml` |

Each node then ran declare, `backup`, `backup-repo-reinit` and `backup-node`, with rc 0 throughout, and had its pin and `targets.txt` regenerated. `own_bucket_nodes` is now `[ace2, beelink, rpi3, rpi4, vps]`. ace2 was born in its own bucket (#2115) and needed no copy.

After the last node's first ship, `make backup-isolation-probe ENV=prod` returned rc 0:
- `40 of 40 cross-node requests refused with AccessDenied` (5 nodes x 4 other buckets, list and delete);
- `every cross-node request and all 5 own deletes were refused`: each node's own delete of its youngest pack was refused by the lock.

This is the prod repeat of scratch step 4, on every bucket.

`toolkit backup escrow-check --env prod` (run from the dotfiles checkout, see dotfiles#2153): 6 of 6 match: the shared password plus ace2, beelink, rpi3, rpi4 and vps.

Still open in the AC1/AC3 task:
- `make watcher-run ENV=prod`, after the sitting PR merges and the watcher reads the new `targets.txt`;
- the seven-day prune window, which starts 2026-10-08.

## The escrow check (AC5, ahead of PR 5)

2026-10-07, run `make backup-escrow-check ENV=prod` with Bitwarden unlocked. Five of five matched: `KUBELAB_RESTIC_PASSWORD` and the four `KUBELAB_RESTIC_PASSWORD_<NODE>` entries against their SOPS values, by sha256[:12], printing no value. This repeats the hand comparison of 2026-10-03, now as a command. I ran five mutations of `backup_escrow.py`, and each turned a test red. One did so only after the test for a password missing from SOPS was made to assert that the escrow is never queried for it.

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
