---
tags: [spec, tasks]
created: "2026-09-30"
---

# Tasks - BACKUP-057

> TDD order. One task = one focused commit. `[P]` = no dependency on another unchecked task. `[AC<n>]` = serves acceptance criterion n in `proposal.md`.
>
> Five PRs, in order. Each leaves prod working: nothing reads a new bucket until PR 4 migrates a node to it.

## Setup

- [x] Branch `feat/backup-057-per-node-r2`, worktree `~/Projects/kubelab-backup-057-wt`
- [x] `proposal.md` complete. Q1-Q3 answered by the operator (#1920, 2026-09-30); bucket name `kubelab-backup-<node>`, repository at the bucket root, approved the same day
- [x] `/spec check BACKUP-057`: PASS-WITH-GAPS (2026-09-30). AC1–AC5 are each covered by `[AC<n>]`-tagged tasks. Two Implementation tasks are untagged, deliberately: the PR 1 measurement gate (Q3) and PR 2's check that the SOPS Cloudflare token can manage R2 buckets and locks, which is a credential prerequisite rather than an outcome. The scratch bucket's destruction is step 6 of the `[AC3]` measurement, not a task of its own

## PR 1 — measure first, and keep measuring (Q3)

The size decides whether R = 30 fits the free tier. It is measured by the watcher rather than by a one-off command, so the number keeps being checked after the lock multiplies retained data.

- [x] [P] [AC2] Failing tests in `tests/test_r2_backup_watcher_probe.py`:
  - each `r2_backup_node` line carries `"raw_bytes":<int>` from `restic stats --mode raw-data --no-lock --json`, and the fleet line carries their sum;
  - a node whose `stats` fails, or that is unreadable, reports `null`, and so does the fleet sum. A partial sum would read as a smaller fleet, which is the one error the size rule must not make;
  - a probe stopped mid-run reports no fleet size.

  The fake restic refuses any `stats` mode other than `raw-data`, so the flag is pinned. The field name and JSON shape of the real image are proven by the staging run below, not by the fake. Expected: FAIL, the field is missing.
- [x] [AC2] `infra/k8s/base/services/r2-backup-watcher/probe.sh`: run `stats` after every health check, under its own `STATS_TIMEOUT`, because `raw-data` walks every tree and the Beelink's outran the 60 s `RESTIC_TIMEOUT` in staging (2026-09-30). Size the timeout, and `activeDeadlineSeconds`, from that measurement. A `stats` failure is logged and marks the size `null`; it never marks a healthy node unhealthy. Expected: PASS.
- [x] [AC2] Failing test, `tests/test_r2_backup_alerting_rules.py`: a Grafana rule `r2-backup-size` fires when the fleet sum exceeds `backup.r2.free_tier_bytes × 0.8`, and pages on no data, which a day of `null` sums is. The threshold is compared with `common.yaml`, never trusted from the rule file. Then add the rule to `grafana-alerting/r2-backup-rules.yaml` and the key to `common.yaml`.
- [x] Deploy to staging, then `make watcher-run ENV=prod`. (Measured by the staging watcher, which reads the same four repositories, 2026-09-30; see `verification.md`. The prod run confirms it after merge.) Record the four sizes and the projection for `--keep-within 31d` in `verification.md`. **Gate:** it passes only with four numeric sizes and a projection that fits the free tier **with both copies stored**. From the first migration in PR 4 until `kubelab-backups` is deleted (at least R + 7 days, Q2), the account holds the old copy, which the watcher no longer sums, and the new one. So the gate compares today's total plus the projected new total against the free tier. A `null` size stops the gate exactly as an overflow does, and R goes back to the operator. The running alert cannot see that old copy, since the watcher no longer sums it, so the gate also checks that the alert's headroom (the free tier minus its 80% threshold) is larger than the old copy as measured: the old copy is frozen at migration, so that one number bounds the alert's blind spot for the whole overlap.

## PR 2 — the R2 Terraform root, measured on a scratch bucket, then applied to the node buckets

- [x] [P] [AC2] Failing test, `tests/test_r2_terraform.py`, run against `toolkit infra terraform r2-tfvars` output. The lock prefixes are declared once, in the renderer, and reach the HCL only as the `locked_prefixes` variable. The test also asserts `main.tf` carries no prefix literal, so the rendered list is the one the lock applies:
  - one bucket per `backup.sources` key, named `kubelab-backup-<node>`;
  - lock prefixes are exactly `data/`, `snapshots/`, `keys/` and `config`, never `locks/` or `index/`;
  - R in days is less than the `--keep-within` days in `node_backup_retention_flags`.
  - `node_backup_retention_flags` carries `--max-repack-size 0`, so `prune` never rewrites a pack and resets its age (proposal *What* §2).

  Expected: FAIL, the command does not exist.
- [x] [AC2] `toolkit infra terraform r2-tfvars` in `toolkit/cli/infra.py`, a plaintext renderer mirroring `vps-firewall-tfvars`. `backup.r2.lock_retention_days: 30` goes into `common.yaml`, and `--keep-within 31d --max-repack-size 0` into `node_backup_retention_flags`. Expected: PASS.
- [x] [AC2] `infra/terraform/r2/`:
  - `required_providers cloudflare ~> 5.8`;
  - `cloudflare_r2_bucket` and `cloudflare_r2_bucket_lock`, each with `for_each` over the rendered nodes;
  - `lifecycle { prevent_destroy = true }` on both;
  - a separate scratch bucket and lock pair, `count`-gated by a variable and **outside** the `for_each`, with no `prevent_destroy`. It cannot be conditional on a variable, so a scratch entry inside the node map could never be destroyed.

  `terraform validate` passes.
- [x] [AC2] `make tf-r2-plan` / `make tf-r2-apply` in the `tf-vps-firewall-*` shape. The Cloudflare token goes in `TF_VAR_*` in the child process's environment, never as an argument.
- [x] Verify by consequence that the SOPS Cloudflare token can manage R2 buckets and locks: `make tf-r2-apply SCRATCH=1` returns rc 0 and creates the scratch bucket with its lock. A plan cannot prove it: planning a resource that does not exist yet makes no R2 call, so a refused token still plans clean (found while building PR 2). This is step 1 of the measurement below. If it is refused, a separate admin token is minted by the operator and added to `SECRET_CATALOG`; record which one it was. Either way, the token that manages the locks is in a file every SOPS recipient decrypts, so record in `verification.md` that #1852 gates the archive (proposal item 1).
- [x] [AC3] Scratch measurement, recorded in `verification.md` (✓ 2026-10-03):
  1. Apply the scratch bucket with R = 1 day, which also confirms the API accepts a short retention.
  2. Point a throwaway restic repository at it and take two `backup`s of different data, so the first snapshot has packs the second does not use, then run `check`. Both must return rc 0. Each `backup` deletes its own file under `locks/`, so this is the measurement that `locks/` is outside the rule. The no-deletion half of the ship proves nothing here: every snapshot is younger than `--keep-within`, so `forget` selects nothing and `prune` issues no DELETE.
  2b. **The repack path, which every other step leaves unexercised.** Take a third `backup` that changes a subset of the second's files, so some packs become partly used, then run `prune --dry-run` twice with the ship's other flags: once without `--max-repack-size 0` and once with it. The first must list at least one pack to repack, and the second none. Otherwise the steps below build only wholly unused packs and never show that the flag stops a rewrite, which is the only path that makes a pack younger than its snapshots (proposal *What* §2).
  3. **The half that can fail: a snapshot younger than R.** `forget <first snapshot id>` with no policy flags (restic does not combine an explicit id with `--keep-*`), then `prune` with the ship's prune flags (`--max-repack-size 0`). restic removes the snapshot file before it prunes, and that file sits under `snapshots/`, younger than R, so the refusal recorded here is the **snapshot's** DELETE, not a pack's. It is the right one to record: when `--keep-within` and R disagree in prod, `forget` selects a snapshot younger than R, and this refusal is the first thing the ship hits. restic must exit non-zero, and the error must be R2's lock refusal (an HTTP 403 for the object). A restic-side error (a flag, a stale repository lock) does not count, and the step is repeated after `restic unlock`. Record the exact error, then show with `restic snapshots` that the first snapshot still exists, and that `restic repair index` and `check` pass.
  3b. Interrupt a `backup` mid-run (kill restic after it has written packs, before the snapshot), then run `prune`. The packs are unreferenced and younger than R, so the delete should be refused. This is the measurement of a refused **pack** DELETE, since no snapshot file is involved. Record whether it is, and restic's exact error: Q6 has decided how the ship reports it, and this is the string the runbook quotes.
  4. A direct delete of a `data/` object younger than R, made with an Object Read & Write token, must be refused.
  5. **The half that must succeed.** More than 24 hours after the **last** write to the repository (step 3b, in this order; whichever step ran last if the order changed), so that the first snapshot, its packs and every leftover are all older than R, confirm with `restic snapshots` that the first snapshot is still listed (otherwise this step would pass without issuing a DELETE). Then run the same `forget <first snapshot id>` and `prune` as in step 3. The deletes must be accepted and restic must exit 0. Afterwards the snapshot must be gone from `restic snapshots`, the pack count under `data/` must have dropped, and `check` must pass. Steps 3 and 4 show only refusals; this is the step that shows the schedule can prune under the lock (#1920 AC2). Without it, a prod where every prune is refused would still pass AC1-AC5.
  6. Destroy the scratch bucket with `-target` after removing its lock rule, and record the steps that took. Destruction waits for step 5.
- [x] [AC2] (✓ 2026-10-03) Once the scratch measurement passes: `make tf-r2-apply` creates the four node buckets and their lock rules, empty. Nothing reads them until PR 4. A second `make tf-r2-plan` shows no diff, which is AC2's evidence. PR 3 depends on this, since a token scoped to a bucket needs the bucket to exist.

## PR 3 — per-node credentials, minted into SOPS (Q1)

- [x] [P] [AC1] (✓ 2026-10-03; the third bullet's watcher config is PR 4, which reads each node's own key) Failing test, `tests/test_backup_node_credentials.py`:
  - `SECRET_CATALOG` declares `backup.r2.nodes.<node>.{access_key_id,secret_access_key}` and `backup.nodes.<node>.restic_password` for every `backup.sources` key;
  - two nodes never share a SOPS path;
  - the watcher has one read-only pair, and reads each node's restic password from that node's own key rather than from a copy.

  Expected: FAIL.
- [x] [AC1] (✓ 2026-10-03) `toolkit backup mint-node-tokens --env prod [--node <n>]`:
  - creates an Object Read & Write token scoped to `kubelab-backup-<node>` through the Cloudflare API and writes the S3 pair straight into SOPS;
  - never prints either value, and verifies each one by consequence (it lists its own bucket, and listing another node's bucket is refused);
  - is idempotent: an existing pair is kept unless `--rotate` is given;
  - also mints the watcher's Object Read token, scoped to the node buckets and to nothing else. Verify by consequence that it lists every node bucket and is refused on `kubelab-backups`. If one token cannot be scoped to several named buckets, the mint stops and says so: the fallback (one read token per node, or an account-wide one) changes proposal item 4 and goes back to the operator.

  Unit tests mock the API and SOPS I/O, following `TestCredentialsGenerateWritesHubKeysToCommon`.
- [x] [AC3] (✓ 2026-10-03) Failing test in `tests/test_backup_per_node_isolation.py`, against the mocked Cloudflare API: the token `toolkit backup mint-node-tokens` requests for each node names exactly one bucket, `kubelab-backup-<node>`, and the watcher's read token names exactly the node buckets. A policy that spans several buckets, or the whole account, fails it. Distinct key pairs alone cannot catch that, so this is the test that makes ticket AC3 fail in CI rather than only at runtime. Expected: FAIL.
- [x] [AC1] (✓ 2026-10-03) `make backup-mint-node-tokens ENV=prod`. Run it and record `make secrets-audit ENV=prod` rc 0 in `verification.md`. Nothing reads the new keys yet.

## PR 4 — every consumer becomes per node, then the migration (Q2)

- [ ] [AC1] Failing tests in a new `tests/test_backup_per_node_isolation.py`, one per consumer: `backup.yml`, `backup_destination.repo_url`, `render_watcher_targets` and the watcher Secret. Each consumer must give every node a bucket, key pair and restic password that no other node gets. They live in their own file so that one run covers them all, with no `-k` filter. The watcher is the one declared exception, by design (proposal *What* §4): its single pair spans every node bucket. For it the test asserts the opposite of the rule: the pair is distinct from every node's pair, the mint command declares it Object Read only, and each restic password it carries comes from that node's own SOPS key, never from a copy. Expected: FAIL.
- [ ] [AC1] Change the consumers:
  - `backup.yml` (both plays) and `backup-repo-reinit.yml`: per-node vars;
  - the `node_backup` role defaults and ship script: the repository URL is `s3:<endpoint>/kubelab-backup-<node>`;
  - `backup_destination.repo_url` / `verify_*`: per-node bucket;
  - `render_watcher_targets`: per-node bucket;
  - `k8s_secrets`: `r2-backup-watcher-secrets` carries the read-only pair plus one restic password per node, keyed by node. The watcher opens every repository (`snapshots`, `stats`), so it needs every password. A test fails if a node in `backup.sources` has no password entry.

  Expected: PASS, `make test` green.
- [ ] [AC3] `forget --prune` runs in `node-backup-prune.service`, not in the ship (Q6, amended 2026-10-03). Failing tests first, in `tests/test_node_backup_prune_script.py` and `tests/test_node_backup_role.py`:
  - the rendered prune script, run against a fake restic, unlocks stale locks, then runs `forget` with the retention flags, `--prune`, `--retry-lock` and the connection option, and exits with restic's code (0 passes, 3 fails);
  - it exits 0 without calling restic when the node has never shipped (no repository marker), so a boot-time `Persistent=` run before the first ship pages nothing;
  - the ship script no longer runs `forget`, and runs `unlock` before `backup`;
  - the prune unit carries `OnFailure=`, its own `TimeoutStartSec` from `node_backup_prune_timeout`, and the ship unit's memory cap; the ship units are `After=` it; the timer is daily and `Persistent=true`; `systemd-analyze verify` accepts every rendered unit;
  - `backup-schedule.yml` arms and disarms the prune timer with the others, and reports each node's prune-unit failures over the last seven days.

  Then measured on one live node: role re-run `changed=0`, the prune unit rc 0, a ship started during a prune waits for it, and a ship after a `kill -9` prune unlocks and succeeds.
- [ ] [AC4] `make backup-migrate NODE=<node> ENV=prod` (toolkit plus an Ansible run, no ad-hoc restic). It runs these steps and stops at the first failure:
  1. `restic copy --from-repo` from `kubelab-backups/<node>` into the new bucket, from the operator workstation.
  2. Compare the snapshot sets from `restic snapshots --json`: every source snapshot's `original` (else its ID) is the `original` of exactly one snapshot in the new bucket. A missing or duplicated one stops the migration.
  3. `backup-repo-reinit` journals the new id.
  4. Deploy the node's new credential.
  5. Ship once.
  6. Re-pin `backup.r2.repository_ids`.

  Tests mock restic and assert the order, and the stop when one source snapshot is missing even though the count and the oldest time match.
- [ ] [AC4] Migrate all four nodes in **one sitting**: until a node's copy finishes, `kubelab-backups` holds its only copy, unlocked. Record per node the number of source snapshots and of matched copies in `verification.md`.
- [ ] [AC1] [AC3] `toolkit backup isolation-probe --env prod` / `make backup-isolation-probe ENV=prod`. For every ordered pair of nodes, node A's credential must be refused on list and delete in node B's bucket. A direct delete of the youngest `data/` object in each bucket, with that node's own credential, must be refused. It exits non-zero if any request is **accepted**, and also if any bucket has no object under `data/`: an empty prefix has nothing to refuse a delete of, so it would report immutability it never measured. It therefore runs after each node's first ship to its bucket, never before. Unit tests mock the S3 client and assert that an accepted request fails the probe. This is what makes the check able to fail: today's shared bucket passes every other check.
- [ ] [AC1] [AC3] Measured in prod, in this order: `make backup-node NODE=all ENV=prod` rc 0, then `make backup-isolation-probe ENV=prod` rc 0, and `make watcher-run ENV=prod` reports `healthy:4`. Then, seven days after the last node migrates, `make alerts` and the Grafana alert history `make backup-schedule NODE=all ENV=prod` reports no `node-backup-prune.service` failure on any node in that window, which is the half of AC3 that rc 0 cannot show (Q6). Record both in `verification.md`.

## PR 5 — close out

- [ ] [AC5] `offsite-backup-restore.md` and `runbook-disaster-recovery.md` state what was measured:
  - per-node isolation;
  - the lock on four prefixes;
  - what it does not cover: the admin token (where it is held; no node has it), data older than R, and a SOPS recipient key (until #1852, every node's history is readable with it, and the Cloudflare token it decrypts can remove a lock rule).

  They also give the recovery procedure for a node whose index was deleted (`restic repair index`).
- [ ] [AC5] `tests/test_offsite_runbook_claims.py`:
  - the runbook names every node bucket derived from `backup.sources`;
  - it names the four locked prefixes and R read from `common.yaml`;
  - it names the three uncovered cases: the admin token, data older than R, and a SOPS recipient key, as both a read and a lock-removal path (the last only while `.sops.yaml` lists more than the operator's key);
  - it no longer claims a single shared bucket.

  The test fails on today's runbook.
- [ ] After AC4 has been verified on all four nodes **and** one weekly `check` has passed on every new bucket: delete `kubelab-backups` and its token, and remove `backup.r2.bucket` / `backup.r2.access_key_id` from `common.yaml` and SOPS. This is its own PR if the weekly check lands after PR 5.

## Closing

- [ ] Every acceptance criterion is covered by a test and has a `features.json` entry with a non-vacuous verification
- [ ] `make test` and lint green
- [ ] #1852 is closed and `.sops.yaml` lists only the human recipient. Until then the lock is liftable through the CI key, so the spec does not archive
- [ ] `verification.md` filled; independent `dotf spec review` (a different model); archive PR closes #1920
