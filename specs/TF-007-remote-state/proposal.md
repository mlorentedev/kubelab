---
id: "TF-007-remote-state"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-10-13"
issue: "mlorentedev/kubelab#558"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, terraform, r2, state]
template_version: "1.0"
wip_override: "Blocks retiring msi: live prod Terraform state has no durable home and three roots already lost theirs (TF-014 #2225) (16 active, limit 10, 2026-10-13)"
---

# TF-007-remote-state

## Why

<!-- from issue #558: TF-007: Evaluate remote state backends (Terraform Cloud free tier vs S3/MinIO) -->

Every Terraform root uses `backend "local"`, so a root's state lives in whichever directory last ran `apply`. Three roots that manage live resources have lost it already: `gcp` and `gcp-bootstrap` were imported inside a worktree that was then removed, and `vps-firewall` was applied on 2026-09-02 from a directory nobody can find. The surviving states (`dns`, `r2`, `aws`) exist only in msi's primary checkout, msi is being retired, and #1499 records the same defect seen from the other side: a plan from a worktree saw an empty state and proposed recreating every DNS record.

## What

Every root keeps its state in the R2 bucket `kubelab-tfstate` under `<root>/terraform.tfstate`, with S3-native locking (`use_lockfile`). ADR-069 records why R2 and why not the alternatives.

- **Backend config fails closed.** Each root declares only `backend "s3" { key = "<root>/terraform.tfstate" }`. The shared settings are in `infra/terraform/backend.s3.tfbackend`, generated from `terraform.state` in `common.yaml`. Without `-backend-config` a `terraform init` stops and asks for the bucket instead of falling back to a local file.
- **One runner for every invocation.** `toolkit infra terraform run <root> <action>` is the only caller of `terraform`. It:
  - renders the root's tfvars into a temporary directory, removed on every exit;
  - injects the provider secrets as `TF_VAR_*` and the backend credentials as `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` into the child process only;
  - always inits against the shared backend file;
  - after any action that writes state, snapshots it to `history/<root>/<lineage>/<serial>.tfstate`, under a 365-day R2 bucket lock.

  The Make targets keep their names and their apply semantics (guarded or interactive per root), and become one line each.
- **The `aws` root stops reading `~/.aws`.** The backend's `AWS_*` variables would outrank the provider's `profile`, so the provider takes the IAM pair from SOPS through `TF_VAR_*`. Registering that pair in `SECRET_CATALOG` closes #1351.
- **Bootstrap is one idempotent command.** `make tf-state-bootstrap` creates the bucket and its lock rule through the Cloudflare API, outside every Terraform root (C16). It then mints an Object Read & Write token scoped to that bucket alone with BACKUP-057's machinery, and proves it by consequence before storing it in SOPS. A second run changes nothing.
- **Migration is one command per root.** `make tf-state-migrate ROOT=<root>` runs in the checkout that holds the local file. It copies the state, compares the resource count before and after, takes the first snapshot, and leaves the local file in place.
- **Proven, not assumed.** `make test-tfstate-lock-live` re-runs the concurrent conditional-write probe against the real bucket.

## Delivery

Two PRs, so the refactor is proven on the backend it already has before the backend moves under it.

- **PR 1a, the runner** (AC3, AC4). Every Make target and toolkit command goes through `toolkit infra terraform run`; the roots keep `backend "local"`. Its proof is that a plan from msi reads the same before and after.
- **PR 1b, the backend** (AC1, AC2, AC5-AC10). Bucket, `.tfbackend`, bootstrap, migration, snapshots, catalog, ADR-069, runbook, lesson.

## Out of scope

- Recovering the lost states of `vps-firewall`, `gcp-bootstrap` and `gcp`: TF-015 (#2226). This PR points those roots at the remote backend with empty state; the runner refuses `apply`/`destroy` on them until TF-015 records them as recovered.
- `oidc-jwks.pem` into SOPS: SEC-030 (#2227).
- Plan in CI, nightly drift detection, the compute deployer key: TF-016 (#2228), TF-017 (#2229), TF-018 (#2230).

## Risks / open questions

- **Atomicity of R2's conditional write is not documented by Cloudflare.** Measured 2026-10-13: 40 trials x 8 concurrent writers, 0 non-atomic. `make test-tfstate-lock-live` re-measures it.
- **R2 has no object versioning.** The locked `history/` prefix replaces it. The lock must never cover the state prefix, or `.tflock` deletes and state writes fail.
- **`encrypt = true` sends an SSE header R2 does not implement.** It stays off; data is encrypted at rest with Cloudflare-managed keys.
- **An empty remote state for a live root is the hazard of #1499 and lesson-369.** The runner keeps a declared list of roots whose state is still unrecovered and refuses state-writing actions on them, naming TF-015.
- **The migration has to run where the local file is**: msi's primary checkout, over ssh. Nothing is deleted there until a plan from the Mac reads `No changes`.

## Acceptance criteria

- [ ] AC1: no root under `infra/terraform/` declares `backend "local"`; each declares `backend "s3"` with `key = "<dir>/terraform.tfstate"` and nothing else (test).
- [ ] AC2: `backend.s3.tfbackend` matches `terraform.state` in `common.yaml` and carries no credential and no `encrypt` (drift test).
- [ ] AC3: nothing outside the runner invokes `terraform` (test over the Makefile and the toolkit).
- [ ] AC4: the runner removes rendered tfvars on success and on failure, propagates terraform's exit code, keeps each root's apply mode, and passes secrets only through the child's environment (tests).
- [ ] AC5: `make tf-state-bootstrap` creates the bucket, the history lock and a scoped token, and a second run reports every step unchanged (unit tests per step, plus the live run recorded in verification.md).
- [ ] AC6: the minted token writes to `kubelab-tfstate` and is refused on a backup bucket, checked by consequence inside the bootstrap.
- [ ] AC7: `dns`, `r2` and `aws` are migrated with the same resource count before and after, and a plan from the Mac reads `No changes` for `dns` and `r2` (live). `aws` is dormant and its plan is reported, never applied.
- [ ] AC8: every state-writing action leaves a snapshot under `history/`, and a repeated snapshot is a no-op (tests + live).
- [ ] AC9: `aws.access_key_id`, `aws.secret_access_key` and `terraform.state.*` are in `SECRET_CATALOG`, and `make secrets-audit` passes.
- [ ] AC10: `docs/runbooks/terraform-state.md` (bootstrap, migrate, restore from history, force-unlock, rotate the token), ADR-069 and lesson-564 land in this PR.

## References

- Epic #2225 (TF-014). Closes #558, #559, #1499, #1351, #554.
- ADR-069 `docs/adr/adr-069-terraform-remote-state-on-r2.md`; ADR-020, ADR-049, ADR-063.
- Vault `30-architecture/session-protocol.md`, C16-C20 and the alternatives rejected on 2026-10-13.
- lesson-369, lesson-375, lesson-453; `specs/BACKUP-057` (token minting precedent).
