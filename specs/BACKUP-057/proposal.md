---
id: "BACKUP-057"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-09-30"
issue: "mlorentedev/kubelab#1920"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-057: one bucket per node, and a lock no node can lift

## Why

<!-- from issue #1920: BACKUP-057: one shared R2 credential can delete every node's backups, and no copy is immutable -->

Every node writes its restic repository to `kubelab-backups` with the same R2 token, which can delete, and the same restic password (`infra/ansible/playbooks/backup.yml:96-98`). Anyone holding one node's credential can delete or rewrite all four histories, and two paths already hand it out: `act_runner` mounts the Docker socket on the Beelink, and the CI age recipient can decrypt `common.enc.yaml`. Nothing declares a bucket lock, so no copy is immutable, and `offsite-backup-restore.md:29` claims an isolation that does not hold. A restore test (#489) proves little while any node can erase what it restores from.

## What

The operator's decision on #1920 (2026-09-30) fixes the shape: one bucket per node, immutability from a per-prefix bucket lock that leaves `locks/` out, and a separate Terraform root on Cloudflare provider v5 so the DNS root keeps `~> 4.0`.

1. **Isolation: one bucket and one credential per node.**
   - Each node in `backup.sources` gets its own bucket, named `kubelab-backup-<node>` with the repository at the bucket root (operator, 2026-09-30), so `backup.r2.bucket` becomes derived per node rather than declared once.
   - Each node gets its own Object Read & Write token, scoped to its own bucket only. Long-lived R2 tokens scope to a bucket and never to a prefix, which is why isolation needs a bucket each.
   - Each node gets its own restic password, so a password leaked **from a node** opens one repository.
   - This isolates the nodes from each other, not the credential store. The minted pairs and passwords live in SOPS (`prod.enc.yaml`), and `.sops.yaml` makes the CI age key a recipient of every `*.enc.yaml`. Whoever holds that key reads all four histories in one decrypt. The same decrypt yields `cloudflare.api_token`, and if that token can manage R2 lock rules (PR 2 measures it), the holder can also remove a rule and delete. So a SOPS recipient key is a delete path as well as a read path, and the lock bounds it only once #1852 (SEC-022, remove the CI recipient; no workflow reads it) has landed. #1852 therefore blocks this spec's archive, not its PRs: each PR leaves prod no weaker than today. Until then the runbook names both halves (AC5).
   - The node keeps running `forget --prune`. A restic writer must hold DeleteObject anyway, since `backup` removes its own lock file under `locks/`, so a separate prune credential held only by the operator would protect nothing. **This amends #1920 AC1**: the protection against a compromised node is the lock in item 2, not a delete-less credential.
2. **Immutability: a lock rule per bucket that no node token can change.**
   - A `cloudflare_r2_bucket_lock` per bucket, with `Age` rules of retention **R** on `data/`, `snapshots/`, `keys/` and `config`.
   - `locks/` and `index/` stay out of the rule. `backup` deletes lock files on every run, and `prune` rewrites and deletes index files on every run. The index can be rebuilt from the packs (`restic repair index`), so leaving it unlocked costs availability, never data. The pre-spec comment on #1920 listed `index/` inside the rule; this corrects it.
   - The retention flags gain `--keep-within <R+1d>` **and `--max-repack-size 0`**. The lock's `Age` is the object's age, and `--keep-within` bounds a snapshot's age, so the two are linked only if no object is ever rewritten. `prune` rewrites: it repacks a partly used pack into a fresh one, whose age restarts at zero while the snapshots it serves are old, and when those snapshots are later forgotten the delete of that young pack is refused. In restic 0.19.1 (`internal/repository/prune.go`, `decidePackAction`), `--max-unused unlimited` does not stop this: tree packs, uncompressed trees and ten or more small packs are repacked whatever that limit says. `--max-repack-size 0` does stop it, because every candidate then hits `reachedRepackSize` and is kept. `forget --prune` accepts the flag (`AddLimitedFlags`).
   - With no repacking, `prune` deletes a pack only when no snapshot uses any of its blobs. A pack is written during a `backup`, before that run's snapshot, so no snapshot that references it is older than the pack. The last such snapshot is forgotten only past 31 days, and 31 > R, so every pack `prune` deletes is older than R. The one exception is a pack that no snapshot ever referenced, which Q6 covers. The claim to measure is that under the lock the scheduled ship and the weekly check succeed.
   - **This changes prod's prune policy**, and it has a cost. Dead blobs in a partly used pack are reclaimed only once the whole pack is unused, so the repository keeps data it no longer needs, and Q3's projection is no longer a steady-state bound. The size alert from PR 1 is what bounds that growth.
   - Lock rules are bucket configuration. Only a token with R2 admin permission can change them. That token is held in SOPS, decrypted on the operator workstation for `tf-r2-*`, and never deployed to a node; until #1852 every SOPS recipient can also decrypt it (item 1). So the lock bounds a compromised node, not a compromised Cloudflare account; the runbook says so.
3. **IaC: a new Terraform root `infra/terraform/r2/`**, pinned to provider v5.
   - Buckets and lock rules are generated from `backup.sources` and `backup.r2`, with the toolkit rendering tfvars from `common.yaml`, the shape `tf-aws-*` already uses.
   - `make tf-r2-plan` and `make tf-r2-apply` follow the same pattern.
4. **Every consumer of the single bucket becomes per node.**
   - The `node_backup` role and its ship script, which build the repository URL.
   - `backup.yml`, which passes the credential and the password per node, and `backup-repo-reinit.yml`.
   - `backup_destination.py`: `repo_url`, `verify_destination`, and `verify_restic`'s scratch repository.
   - The watcher: `render_watcher_targets` gains a bucket per line. `r2-backup-watcher-secrets` gains one read-only token scoped to all node buckets, plus every node's restic password, since the watcher opens each repository. So the watcher secret can **read** every history, and it can delete none. The runbook states this.
   - `SECRET_CATALOG` and the `secrets-audit` expectations.
   - `offsite-backup-restore.md` and `runbook-disaster-recovery.md`.
   - The tests that pin the single-bucket shape (`test_backup_destination`, `test_r2_watcher_targets`, `test_k8s_secrets_r2_watcher`, `test_node_backup_role`, `test_node_backup_ship_script`).
5. **Migration without losing history, and without fighting BACKUP-058.** A new bucket holds a new repository, so the node's recorded repository id no longer matches and the ship refuses. That refusal is by design (#1938, #1947). For each node, from the operator workstation:
   1. `restic copy` from `kubelab-backups/<node>` into the new bucket, which keeps the snapshots.
   2. `make backup-repo-reinit NODE=<node> DEST=r2 ENV=prod`, which journals the id it forgets.
   3. Deploy the node's new credential, run one ship, and re-pin the watcher's `repository_ids`.

   `kubelab-backups` is not deleted by this spec.

## Out of scope

- Temporary, locally signed R2 credentials (prefix and action scoping). They would need a renewer outside the node every 7 days at most, against the fleet's "no new services" rule.
- Bumping the DNS root's `cloudflare` provider to v5.
- Any change to `backup.sources`, to what each node backs up, or to the schedule.
- Deleting or importing `kubelab-backups` (see Risks Q2). It stays in place until the close-out task deletes it: after AC4 is verified on all four nodes and one weekly `check` has passed on every new bucket. That task is the only deletion gate.
- The Storage Box leg (#471). Its credential model is a separate decision.

## Risks / open questions

Q1 to Q3 were answered by the operator on 2026-09-30 (#1920, comment "Operator answers to BACKUP-057 Q1-Q3").

- **Q1, resolved: a toolkit command mints the tokens.** It creates each token through the Cloudflare API and writes the S3 pair straight into SOPS, with no state file, following the same pattern as `credentials generate`. The rejected option was `cloudflare_api_token` in the R2 root: that would leave four plaintext secrets in `terraform.tfstate` (local and gitignored, `infra/terraform/.gitignore:4`), a second copy of each secret. The command uses the Cloudflare admin token, which is also the only credential that can change or remove a lock rule. The runbook names where it is held (the operator workstation) and states that no node ever receives it.
- **Q2, resolved: `kubelab-backups` stays unmanaged, and its deletion is gated on evidence, not on a date.** It is deleted once AC4 is verified on all four nodes **and** every new bucket has passed one weekly `check`. Until `restic copy` has finished for a node, the old bucket holds that node's only copy, and nothing locks it. The migration therefore runs as one task from start to finish, not spread across sessions.
- **Q3, resolved: R = 30 days, `--keep-within 31d`.** R is fixed in code only after measurement. The first task measures the current size of the four repositories and records it against the free tier (10 GB-month; overage is billed, with no hard stop, per the `common.yaml` R2 comment). If the projected total with 31 days of dailies exceeds the free tier, R comes back to the operator before the lock is applied. The AC2 test pins `keep-within > R` as a relation. With `--max-repack-size 0` (*What* §2), the projection is a bound only until partly used packs start to accumulate. From then on, the size alert bounds growth.
- **Q4 (resolved by the scratch measurement in `tasks.md` PR 2, not blocking): measure before prod.** The Age condition cannot be fast-forwarded, so a scratch bucket cannot age a snapshot past R. The scratch test proves the other half:
  - with the lock in place, `backup` succeeds, which proves that `locks/` is outside the rule;
  - a `prune` forced to delete a young pack (`forget <id> --prune`) is refused, and restic exits non-zero (rc 3 for a snapshot; a refused pack exits 0, measured in step 3b), which is the failure Q6's prune unit reports;
  - a direct delete of a young object under `data/` is refused.

  A scheduled ship succeeding **with** the lock is proved only in prod, over time, because `--keep-within` and `--max-repack-size 0` together keep every young pack referenced (*What* §2).

  R2 documents no minimum or maximum retention for a lock rule. The scratch test uses R = 1 day to confirm that the API accepts a short value.
- **Q5: removing a lock rule.** Cloudflare documents removing rules only as a whole ("Remove all lock rules before emptying a bucket"). A Terraform change that removes or shortens a rule is therefore an admin action, and it has to be visible in `tf-r2-plan` output, never applied as a side effect. The root sets `prevent_destroy` on the lock resources.
- **Q6, decided here, amended 2026-10-03 by the operator: `forget --prune` leaves the ship for a unit of its own.** restic writes packs before the snapshot, so a node powered off mid-run (the normal state of an on-demand node) leaves packs no snapshot references. `--keep-within` cannot keep them, and the next `prune` deletes unreferenced packs whatever their age. Under the lock that delete is refused. The snapshot was already written and locked, so nothing is lost. The scratch measurements (`verification.md`, steps 3 and 3b) then decided the shape:
  - restic retries a refused DELETE for about 15 minutes, with no knob that shortens it, longer than the ship's `TimeoutStartSec=600`. Removes run in parallel up to the S3 connection count (`ParallelRemove`, 5 by default in 0.19.1), so k refused packs cost about ⌈k/connections⌉ × 15 minutes.
  - A refused **pack** DELETE exits **0**; a refused **snapshot** DELETE exits **3**.

  **The decision.** `node-backup-prune.service` runs `forget <retention> --prune` once a day (`node-backup-prune.timer`, `OnCalendar=daily`, `Persistent=true`), with its own `TimeoutStartSec` (`node_backup_prune_timeout`, 3600 s), its own `OnFailure=` notification, and `-o s3.connections=20` (`node_backup_prune_connections`), so the bound covers about 80 refused packs (about 1.3 GB of interrupted upload). The ship no longer prunes; only a failed `backup` or `check` fails it. The prune unit fails, and notifies, on any non-zero exit: a refused snapshot (rc 3) cannot happen while `--keep-within` exceeds R, so it is a real fault. A refused pack (rc 0) is the expected, harmless case and pages nothing. Its only cost is storage for at most R days, which the `r2-backup-size` alert already bounds. No signal reads restic's output text. Coordination: the prune takes the exclusive lock with `--retry-lock 10m`, which outlasts a ship; the ship units are `After=` the prune unit, so a ship queued during a prune waits for it. A killed prune leaves a lock that restic 0.19.1 never skips (`checkForOtherLocks` does not test `Stale()`), so both the ship and the prune run `restic unlock` (stale locks only) first. Every read the ship makes before that `unlock` (the reachability probe, `cat config`) runs with `--no-lock`: a read that locks fails on the stale lock with exit 11 before `unlock` is reached (measured on beelink 2026-10-04, lesson-521).

  *Original Q6, superseded:* the ship records the `backup` and `prune` outcomes separately, a failed `prune` after a successful `backup` gets its own signal, and the prune stays in the ship.
- **The restic password per node** changes the SOPS layout (`backup.restic_password` becomes per node). `restic copy` needs both passwords during migration (`--from-password-file`).

## Acceptance criteria

- [ ] **AC1**: Each node in `backup.sources` ships to its own R2 bucket with a credential scoped to that bucket only. A test fails if the rendered configuration gives a node a bucket or a credential shared with another node. Measured in prod: with node A's credential, listing or deleting in node B's bucket is refused. This amends #1920 AC1 as explained in *What* §1.
- [ ] **AC2**: Every node bucket has a lock rule declared in `infra/terraform/r2/`, on `data/`, `snapshots/`, `keys/` and `config`, never on `locks/` or `index/`. `make tf-r2-plan` shows no diff after apply. A test fails if a rule covers `locks/` or `index/`, if R ≥ the `--keep-within` value in the retention flags, or if those flags lack `--max-repack-size 0`. Before any lock is applied, the watcher reports every node's raw repository size and the fleet sum, the `r2-backup-size` rule fires above 80% of the declared free tier, and the projected size for `--keep-within 31d` is recorded under that line (Q3): R = 30 is only chosen if it fits. **This amends #1920 AC2** in two ways: the lock is on the per-node buckets, not on `kubelab-backups`, which stays unlocked until it is deleted (Q2); and R is **shorter** than the forget window, not longer as the ticket asks, because a lock that outlives the window refuses the delete of every pack `forget` releases, so every scheduled `prune` would fail.
- [ ] **AC3**: Under the lock, the scheduled ship and the weekly `check` succeed on every node: `make backup-node NODE=all ENV=prod` returns rc 0, the watcher reports `healthy:4`, and no node's `node-backup-prune.service` fails in the seven days after the last node migrates (`make backup-schedule NODE=all ENV=prod` reports the count per node). The ship no longer prunes (Q6), so rc 0 and `healthy:4` alone would pass with every prune failing. A direct delete of a young `data/` object with a node's credential is refused, which is measured on the scratch bucket and then on one prod bucket.
- [ ] **AC4**: Every node's history before the migration survives it. Every snapshot in `kubelab-backups/<node>` at copy time has exactly one copy in the new bucket, matched by restic's `original` field: `restic copy` gives each copy a new ID and records the source's there (the source's own `original` when it has one, else its ID). Count and oldest time alone would not do, since different sets can share both. The watcher's `repository_ids` are re-pinned, and no refusal from BACKUP-058 was overridden without its journal line.
- [ ] **AC5**: `offsite-backup-restore.md` states the isolation and immutability that were measured, and what they do not cover: an admin token, data older than R, and, until #1852 lands, any holder of a SOPS recipient key, who can read every node's history and, through the Cloudflare token in the same files, remove a lock rule and delete.

Mapping to #1920's criteria: its AC1 is AC1 here (amended), its AC2 is AC2 and AC3 (amended), its AC3 is the test in AC1, and its AC4 is AC5. AC4 here, the migration, is new: the ticket had a single bucket and nothing to migrate.

## References

- Issue: mlorentedev/kubelab#1920 (decision comment 2026-09-30). Epic: #1923.
- Depends on: #1938 and #1947 (BACKUP-058, the repository-id marker and the watcher pin).
- Related ADRs: `docs/adr/adr-049-*` (R2 as the offsite destination), `docs/adr/adr-028-*` (always-on and on-demand).
- Cloudflare: R2 API tokens, temporary credentials, and bucket locks (links in the pre-spec comment on #1920).
