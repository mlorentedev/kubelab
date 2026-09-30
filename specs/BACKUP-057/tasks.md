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
- [x] `/spec check BACKUP-057`: PASS-WITH-GAPS (2026-09-30). AC1–AC5 are each covered by `[AC<n>]`-tagged tasks. The two untagged tasks are deliberate: the PR 1 measurement gate (Q3) and the scratch measurement's cleanup

## PR 1 — measure first, and keep measuring (Q3)

The size decides whether R = 30 fits the free tier. It is measured by the watcher rather than by a one-off command, so the number keeps being checked after the lock multiplies retained data.

- [ ] [P] [AC2] Failing test in `tests/test_r2_backup_watcher_probe.py`: the `r2_backup_node` line carries `"raw_bytes":<int>` from `restic stats --mode raw-data --no-lock --json`, and the fleet line carries its sum. The fake restic returns a fixed `total_size`. Expected: FAIL, the field is missing.
- [ ] [AC2] `infra/k8s/base/services/r2-backup-watcher/probe.sh`: run `stats` after `snapshots`, under the same `RESTIC_TIMEOUT`, and emit both fields. A `stats` failure is logged and marks the size unknown (`null`); it never marks a healthy node unhealthy. Expected: PASS.
- [ ] [AC2] Failing test, `tests/test_r2_backup_rules.py`: a Grafana rule `r2-backup-size` fires when the fleet sum exceeds `backup.r2.free_tier_bytes × 0.8`. The threshold is read from `common.yaml`, never hardcoded. Then add the rule to `grafana-alerting/r2-backup-rules.yaml` and the key to `common.yaml`.
- [ ] Deploy to staging, then `make watcher-run ENV=prod`. Record the four sizes and the projection for `--keep-within 31d` in `verification.md`. **Gate:** if the projection exceeds the free tier, stop and return R to the operator.

## PR 2 — the R2 Terraform root, applied to a scratch bucket only

- [ ] [P] [AC2] Failing test, `tests/test_r2_terraform.py`, run against `toolkit infra terraform r2-tfvars` output:
  - one bucket per `backup.sources` key, named `kubelab-backup-<node>`;
  - lock prefixes are exactly `data/`, `snapshots/`, `keys/` and `config`, never `locks/` or `index/`;
  - R in days is less than the `--keep-within` days in `node_backup_retention_flags`.

  Expected: FAIL, the command does not exist.
- [ ] [AC2] `toolkit infra terraform r2-tfvars` in `toolkit/cli/infra.py`, a plaintext renderer mirroring `vps-firewall-tfvars`. `backup.r2.lock_retention_days: 30` goes into `common.yaml`, and `--keep-within 31d` into `node_backup_retention_flags`. Expected: PASS.
- [ ] [AC2] `infra/terraform/r2/`:
  - `required_providers cloudflare ~> 5.8`;
  - `cloudflare_r2_bucket` and `cloudflare_r2_bucket_lock`, each with `for_each` over the rendered nodes;
  - `lifecycle { prevent_destroy = true }` on both;
  - a separate scratch bucket and lock pair, `count`-gated by a variable and **outside** the `for_each`, with no `prevent_destroy`. It cannot be conditional on a variable, so a scratch entry inside the node map could never be destroyed.

  `terraform validate` passes.
- [ ] [AC2] `make tf-r2-plan` / `make tf-r2-apply` in the `tf-vps-firewall-*` shape. The Cloudflare token goes in `TF_VAR_*` in the child process's environment, never as an argument.
- [ ] Verify by consequence that the SOPS Cloudflare token can manage R2 buckets and locks: `make tf-r2-plan` with `nodes = {}` and `scratch = true` returns rc 0. If it is refused, a separate admin token is minted by the operator and added to `SECRET_CATALOG`; record which one it was.
- [ ] [AC3] Scratch measurement, recorded in `verification.md`:
  1. Apply the scratch bucket with R = 1 day, which also confirms the API accepts a short retention.
  2. Point a throwaway restic repository at it and run `backup`, `forget --keep-within 2d --prune` and `check`. All must return rc 0.
  3. A direct delete of a `data/` object younger than R, made with an Object Read & Write token, must be refused.
  4. `rm` of a `locks/` object must succeed.
  5. Destroy the scratch bucket with `-target` after removing its lock rule, and record the steps that took.

## PR 3 — per-node credentials, minted into SOPS (Q1)

- [ ] [P] [AC1] Failing test, `tests/test_backup_node_credentials.py`:
  - `SECRET_CATALOG` declares `backup.r2.nodes.<node>.{access_key_id,secret_access_key}` and `backup.nodes.<node>.restic_password` for every `backup.sources` key;
  - two nodes never share a SOPS path;
  - the watcher has one read-only pair.

  Expected: FAIL.
- [ ] [AC1] `toolkit backup mint-node-tokens --env prod [--node <n>]`:
  - creates an Object Read & Write token scoped to `kubelab-backup-<node>` through the Cloudflare API and writes the S3 pair straight into SOPS;
  - never prints either value, and verifies each one by consequence (it lists its own bucket, and listing another node's bucket is refused);
  - is idempotent: an existing pair is kept unless `--rotate` is given;
  - also mints the watcher's Object Read token, scoped to all node buckets.

  Unit tests mock the API and SOPS I/O, following `TestCredentialsGenerateWritesHubKeysToCommon`.
- [ ] [AC1] `make backup-mint-node-tokens ENV=prod`. Run it and record `make secrets-audit ENV=prod` rc 0 in `verification.md`. Nothing reads the new keys yet.

## PR 4 — every consumer becomes per node, then the migration (Q2)

- [ ] [AC1] Failing test: rendering `backup.yml` for each node yields a bucket, key pair and restic password that no other node gets. Covers `test_node_backup_role` and `test_backup_destination`; `test_r2_watcher_targets` gains the bucket column. Expected: FAIL.
- [ ] [AC1] Change the consumers:
  - `backup.yml` (both plays) and `backup-repo-reinit.yml`: per-node vars;
  - the `node_backup` role defaults and ship script: the repository URL is `s3:<endpoint>/kubelab-backup-<node>`;
  - `backup_destination.repo_url` / `verify_*`: per-node bucket;
  - `render_watcher_targets`: per-node bucket;
  - `k8s_secrets`: the watcher's read-only pair.

  Expected: PASS, `make test` green.
- [ ] [AC4] `make backup-migrate NODE=<node> ENV=prod` (toolkit plus an Ansible run, no ad-hoc restic). It runs these steps and stops at the first failure:
  1. `restic copy --from-repo` from `kubelab-backups/<node>` into the new bucket, from the operator workstation.
  2. Compare the snapshot count and the oldest snapshot time with the source.
  3. `backup-repo-reinit` journals the new id.
  4. Deploy the node's new credential.
  5. Ship once.
  6. Re-pin `backup.r2.repository_ids`.

  Tests mock restic and assert the order and the stop on mismatch.
- [ ] [AC4] Migrate all four nodes in **one sitting**: until a node's copy finishes, `kubelab-backups` holds its only copy, unlocked. Record per-node counts and times in `verification.md`.
- [ ] [AC1] [AC3] Measured in prod:
  - with node A's credential, list and delete in node B's bucket are refused;
  - `make backup-node NODE=all ENV=prod` rc 0;
  - `make watcher-run ENV=prod` reports `healthy:4`;
  - one direct delete of a young `data/` object in one prod bucket is refused.

## PR 5 — close out

- [ ] [AC5] `offsite-backup-restore.md` and `runbook-disaster-recovery.md` state what was measured:
  - per-node isolation;
  - the lock on four prefixes;
  - what it does not cover: the admin token (where it is held; no node has it) and data older than R.

  They also give the recovery procedure for a node whose index was deleted (`restic repair index`).
- [ ] After AC4 has been verified on all four nodes **and** one weekly `check` has passed on every new bucket: delete `kubelab-backups` and its token, and remove `backup.r2.bucket` / `backup.r2.access_key_id` from `common.yaml` and SOPS. This is its own PR if the weekly check lands after PR 5.

## Closing

- [ ] Every acceptance criterion is covered by a test and has a `features.json` entry with a non-vacuous verification
- [ ] `make test` and lint green
- [ ] `verification.md` filled; independent `dotf spec review` (a different model); archive PR closes #1920
