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
   - Each node in `backup.sources` gets its own bucket. [AGENT-DRAFT — review before archive] Proposed name `kubelab-backup-<node>`, with the repository at the bucket root, so `backup.r2.bucket` becomes derived per node rather than declared once.
   - Each node gets its own Object Read & Write token, scoped to its own bucket only. Long-lived R2 tokens scope to a bucket and never to a prefix, which is why isolation needs a bucket each.
   - Each node gets its own restic password, so a leaked password opens one repository.
   - The node keeps running `forget --prune`. A restic writer must hold DeleteObject anyway, since `backup` removes its own lock file under `locks/`, so a separate prune credential held only by the operator would protect nothing. **This amends #1920 AC1**: the protection against a compromised node is the lock in item 2, not a delete-less credential.
2. **Immutability: a lock rule per bucket that no node token can change.**
   - A `cloudflare_r2_bucket_lock` per bucket, with `Age` rules of retention **R** on `data/`, `snapshots/`, `keys/` and `config`.
   - `locks/` and `index/` stay out of the rule. `backup` deletes lock files on every run, and `prune` rewrites and deletes index files on every run. The index can be rebuilt from the packs (`restic repair index`), so leaving it unlocked costs availability, never data. The pre-spec comment on #1920 listed `index/` inside the rule; this corrects it.
   - The retention flags gain `--keep-within <R+1d>`. With it, nothing younger than R is ever forgotten, so `prune` never needs to delete an object younger than R. The claim to measure is exactly that: under the lock, the scheduled ship and weekly check succeed.
   - Lock rules are bucket configuration. Only an admin token can change them, and that token lives on the operator workstation and in Terraform, never on a node. So the lock bounds a compromised node, not a compromised Cloudflare account; the runbook says so.
3. **IaC: a new Terraform root `infra/terraform/r2/`**, pinned to provider v5.
   - Buckets and lock rules are generated from `backup.sources` and `backup.r2`, with the toolkit rendering tfvars from `common.yaml`, the shape `tf-aws-*` already uses.
   - `make tf-r2-plan` and `make tf-r2-apply` follow the same pattern.
4. **Every consumer of the single bucket becomes per node.**
   - The `node_backup` role and its ship script, which build the repository URL.
   - `backup.yml`, which passes the credential and the password per node, and `backup-repo-reinit.yml`.
   - `backup_destination.py`: `repo_url`, `verify_destination`, and `verify_restic`'s scratch repository.
   - The watcher: `render_watcher_targets` gains a bucket per line, and `r2-backup-watcher-secrets` gains one read-only token scoped to all node buckets.
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
- Deleting or importing `kubelab-backups` (see Risks Q2). It stays read-only in place until the retention window of the new buckets covers what it holds.
- The Storage Box leg (#471). Its credential model is a separate decision.

## Risks / open questions

Q1 to Q3 were answered by the operator on 2026-09-30 (#1920, comment "Operator answers to BACKUP-057 Q1-Q3").

- **Q1, resolved: a toolkit command mints the tokens.** It creates each token through the Cloudflare API and writes the S3 pair straight into SOPS, with no state file, following the same pattern as `credentials generate`. The rejected option was `cloudflare_api_token` in the R2 root: that would leave four plaintext secrets in `terraform.tfstate` (local and gitignored, `infra/terraform/.gitignore:4`), a second copy of each secret. The command uses the Cloudflare admin token, which is also the only credential that can change or remove a lock rule. The runbook names where it is held (the operator workstation) and states that no node ever receives it.
- **Q2, resolved: `kubelab-backups` stays unmanaged, and its deletion is gated on evidence, not on a date.** It is deleted once AC4 is verified on all four nodes **and** every new bucket has passed one weekly `check`. Until `restic copy` has finished for a node, the old bucket holds that node's only copy, and nothing locks it. The migration therefore runs as one task from start to finish, not spread across sessions.
- **Q3, resolved: R = 30 days, `--keep-within 31d`.** R is fixed in code only after measurement. The first task measures the current size of the four repositories and records it against the free tier (10 GB-month; overage is billed, with no hard stop, per the `common.yaml` R2 comment). If the projected total with 31 days of dailies exceeds the free tier, R comes back to the operator before the lock is applied. The AC2 test pins `keep-within > R` as a relation.
- **Q4 (resolved in PR 1, not blocking): measure before prod.** The Age condition cannot be fast-forwarded, so a scratch bucket cannot age a snapshot past R. The scratch test proves the other half:
  - with the lock in place, a full ship (`backup`, `forget --keep-within`, `prune`) succeeds;
  - a direct delete of a young object under `data/` is refused;
  - restic run against that refusal fails the ship, which pages.

  R2 documents no minimum or maximum retention for a lock rule. The scratch test uses R = 1 day to confirm that the API accepts a short value.
- **Q5: removing a lock rule.** Cloudflare documents removing rules only as a whole ("Remove all lock rules before emptying a bucket"). A Terraform change that removes or shortens a rule is therefore an admin action, and it has to be visible in `tf-r2-plan` output, never applied as a side effect. The root sets `prevent_destroy` on the lock resources.
- **The restic password per node** changes the SOPS layout (`backup.restic_password` becomes per node). `restic copy` needs both passwords during migration (`--from-password-file`).

## Acceptance criteria

- [ ] **AC1**: Each node in `backup.sources` ships to its own R2 bucket with a credential scoped to that bucket only. A test fails if the rendered configuration gives a node a bucket or a credential shared with another node. Measured in prod: with node A's credential, listing or deleting in node B's bucket is refused. This amends #1920 AC1 as explained in *What* §1.
- [ ] **AC2**: Every node bucket has a lock rule declared in `infra/terraform/r2/`, on `data/`, `snapshots/`, `keys/` and `config`, never on `locks/` or `index/`. `make tf-r2-plan` shows no diff after apply. A test fails if a rule covers `locks/` or `index/`, or if R ≥ the `--keep-within` value in the retention flags.
- [ ] **AC3**: Under the lock, the scheduled ship and the weekly `check` succeed on every node: `make backup-node NODE=all ENV=prod` returns rc 0, and the watcher reports `healthy:4`. A direct delete of a young `data/` object with a node's credential is refused, which is measured on the scratch bucket and then on one prod bucket.
- [ ] **AC4**: Every node's history before the migration survives it. Snapshot count and oldest snapshot time in the new bucket are ≥ those in `kubelab-backups/<node>` at copy time. The watcher's `repository_ids` are re-pinned, and no refusal from BACKUP-058 was overridden without its journal line.
- [ ] **AC5**: `offsite-backup-restore.md` states the isolation and immutability that were measured, and what the lock does not cover (an admin token, and data older than R).

## References

- Issue: mlorentedev/kubelab#1920 (decision comment 2026-09-30). Epic: #1923.
- Depends on: #1938 and #1947 (BACKUP-058, the repository-id marker and the watcher pin).
- Related ADRs: `docs/adr/adr-049-*` (R2 as the offsite destination), `docs/adr/adr-028-*` (always-on and on-demand).
- Cloudflare: R2 API tokens, temporary credentials, and bucket locks (links in the pre-spec comment on #1920).
