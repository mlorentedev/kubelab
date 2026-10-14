---
id: "adr-069"
type: adr
status: accepted
owner: manu
date: "2026-10-13"
issue: "kubelab#558"
tags: [architecture, decision, terraform, state, r2, secrets, iac]
depends_on: [adr-014-secrets-management-strategy, adr-020-iac-lifecycle-strategy, adr-049-edge-object-storage-placement-doctrine, adr-063-hub-cloud-provider-migration]
created: "2026-10-13"
---

# ADR-069: Terraform State Lives in R2, Behind One Runner

## Status

Accepted, 2026-10-13. The operator chose this option during an architecture session on kubelab#558 (TF-007), within epic TF-014 (#2225). Spec: `specs/TF-007-remote-state/`.

## Context

Every Terraform root under `infra/terraform/` used `backend "local"`, so a root's state lived in whichever directory last ran `apply`, and nowhere else.

- Three roots that manage live resources lost their state that way. `gcp` and `gcp-bootstrap` were imported inside a worktree that was later removed. `vps-firewall` was applied on 2026-09-02 from a directory nobody can find. Their recovery is TF-015 (#2226).
- The surviving states (`dns`, `r2`, `aws`) existed only in msi's primary checkout, and msi is being retired.
- #1499 is the same defect seen from the other side: a plan from a worktree read an empty state and proposed recreating every DNS record (lesson-369).
- The `aws` provider read `~/.aws`, a machine-local credential with no copy in SOPS (#1351).

The state also holds plaintext secrets (the `r2` root's tokens, for one), so wherever it goes is a secrets store.

Constraints the decision is held to (vault `30-architecture/session-protocol.md`):

| # | Constraint |
|---|---|
| C16 | Layer 0 stands alone: state, and anything the bootstrap path needs, never lives in a resource some Terraform root manages. |
| C17 | Every credential an IaC run needs comes from SOPS; a workstation needs only the age key. |
| C18 | State needs a credential scoped to it, encryption at rest, an immutable history, and no vendor able to read it. |
| C19 | Locking holds across parallel lanes and worktrees: state never lives in a working directory. |
| C20 | Data stays off the GCP data plane: the hub project can lose billing to its kill switch. |

## Options Considered

| Option | Verdict | Reconsider when |
|---|---|---|
| **R2 bucket `kubelab-tfstate`, S3 backend with `use_lockfile`** | **Chosen.** Same account as the backups, no new vendor, scoped tokens, conditional writes. | — |
| HCP Terraform free tier | Rejected: the vendor can read state that holds plaintext secrets (C18), the ground on which ADR-014 rejected cloud secret stores. | State is encrypted client-side (an OpenTofu move). |
| `pg` backend on the prod Postgres | Rejected: circular, `vps-firewall` and `compute` manage the host it runs on (C16). | A Postgres exists that no root manages. |
| GCS bucket in `kubelab-hub` | Rejected: the kill switch detaches billing from that project (C20), and `gcp-bootstrap` manages it (C16). | The bucket moves to a project with no kill switch. |
| AWS S3 | Rejected: it keeps alive an account ADR-063 retired, for one bucket. | R2's conditional writes stop being atomic, or R2 leaves the stack. |

## Decision

1. **Backend.** Each root declares only `backend "s3" { key = "<root>/terraform.tfstate" }` and requires Terraform `>= 1.10`. The shared settings are one generated file, `infra/terraform/backend.s3.tfbackend`, rendered from `terraform.state` in `common.yaml` (`make sync-terraform-backend`, drift-tested). A root initialised without it asks for the bucket: there is no setting under which it falls back to a local file. Locking is S3-native (`use_lockfile`, a conditional PUT of `<key>.tflock`). `encrypt` stays off: it sends an SSE header R2 does not implement, and R2 encrypts at rest regardless.
2. **One runner.** `toolkit infra terraform run <root> <action>` is the only caller of `terraform` (a test enforces it). It renders tfvars into a temporary directory, passes provider secrets as `TF_VAR_*` and the state credential as `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY` to the child only, and always runs `init -reconfigure` against the shared backend file.
3. **History instead of versioning.** R2 has no object versioning. Before and after every action that writes state, the runner copies it to `history/<root>/<lineage>/<serial>.tfstate` with a create-only PUT. A bucket lock rule retains everything under `history/` for 365 days, so a copy can be neither overwritten nor deleted in that time. The lock never covers the state keys, or `.tflock` deletes and state writes would fail. A failed snapshot before a write refuses the write.
4. **Bootstrap outside Terraform (C16).** `make tf-state-bootstrap` creates the bucket and its lock rule through the Cloudflare API, then mints an Object Read & Write token scoped to that bucket with BACKUP-057's machinery. It proves the token by consequence, so the token must list the state bucket and be refused on the backups bucket, before storing the pair in `common.enc.yaml`. Each step reads first and writes only what differs.
5. **Guards against the empty-state hazard.** The runner refuses any action while a local `terraform.tfstate` sits in the root, except `migrate`, which pushes it without `-force`. It accepts the push only if the remote state has the same lineage and the same resource addresses, at a serial no lower than the local one, then renames the local file to `terraform.pre-remote.tfstate`. Roots whose state is still lost (`gcp`, `gcp-bootstrap`, `vps-firewall`) are declared unrecovered, and the runner refuses `apply`, `destroy` and `untaint` on them, naming TF-015.
6. **The `aws` provider takes its IAM pair from SOPS.** The backend's `AWS_*` variables would outrank a provider `profile`, so the profile is removed and `aws.access_key_id`/`aws.secret_access_key` are registered in `SECRET_CATALOG` (closes #1351).

## Rationale

- R2 is already a dependency of Layer 0 (backups, ADR-049), and nothing a Terraform root manages hosts it, since the `r2` root manages other buckets but not this one.
- Cloudflare does not document the atomicity of R2's conditional writes, which `use_lockfile` relies on. It was measured instead: 40 trials of 8 concurrent writers, 0 non-atomic (2026-10-13). `make test-tfstate-lock-live` re-measures it against the real bucket.
- The runner is what makes the backend safe to adopt. Without it, credentials would sit in the shell, and a shell `AWS_*` or `AWS_PROFILE` would quietly steer `init` or the history copy at the wrong account (lesson-563).

## Consequences

**Positive**
- Any checkout on any machine with the age key plans against the same state, under one lock.
- A state can be restored from `history/` for a year, and nobody can delete that copy.
- msi can be retired once `dns`, `r2` and `aws` are migrated and the Mac plans `No changes`.

**Negative**
- Every Terraform run depends on R2 being reachable and on one SOPS-held token. Rotation: `make tf-state-bootstrap ROTATE=1`.
- R2's lock atomicity is measured, not promised. The live probe is how a regression would be seen.
- History accumulates for 365 days with no way to delete early. It is small (one object per state write).

**Neutral**
- The three lost states stay lost until TF-015. Their roots point at empty remote keys, behind the runner's refusal.
- Plan in CI and nightly drift detection build on this (TF-016, TF-017).

## References

- Spec `specs/TF-007-remote-state/`; runbook `docs/runbooks/terraform-state.md`; lesson-564.
- Issues #558, #1499, #1351, epic #2225, TF-015 #2226.
- ADR-014 (secrets), ADR-020 (Layer 0), ADR-049 (object storage placement), ADR-063 (GCP plane, kill switch).
- lesson-369, lesson-563; `specs/BACKUP-057` (token minting).
