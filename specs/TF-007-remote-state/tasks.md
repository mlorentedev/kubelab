---
tags: [spec, tasks]
created: "2026-10-13"
---

# Tasks - TF-007-remote-state

## PR 1a: one runner (`feature/terraform-runner`)

- [x] [AC3] `tests/test_terraform_single_entry.py`: no Make recipe runs `terraform` or `cd infra/terraform`; no toolkit call spawns it outside the runner; each tf target is one `$(_TF)` line.
- [x] [AC4] `tests/test_terraform_runner.py`: init first, secrets only in the child env, inherited `AWS_*`/`TF_VAR_*` stripped, tfvars in a 0600 temp dir removed on success, failure and KeyboardInterrupt, legacy rendered files removed, apply mode per root, exit code propagated.
- [x] [AC4] `toolkit/features/terraform_runner.py` and `toolkit infra terraform run`; the seven `*-tfvars` commands, `plan-guard`, `validate` and the env-based `init/plan/apply/destroy` removed.
- [x] [AC4] `vps_firewall_tfvars.render` extracted from the CLI, with its own tests.
- [x] [AC4] `aws1-replace` uses the guarded apply with `--allow`, no `-auto-approve`; `gcp-killswitch-prove` tears down in a `finally`.
- [x] Comments, READMEs and test messages that named the removed commands point at the runner.
- [x] `terraform fmt` pre-commit hook (`compute/main.tf` had drifted unnoticed); the CI gate is TF-016.
- [x] `make mutate`: seven mutations, all RED (raw terraform in a recipe, dns destroy always allowed, legacy renders kept, inherited `TF_VAR_*` kept, guard ignored, tfvars 0644, a missing var file). Found and fixed a `make mutate` bytecode defect on the way: #2235, lesson-562.
- [x] msi: `make tf-dns-plan` and `make tf-r2-plan` read `No changes` on master and on this branch (2026-10-13, operator-approved, msi returned to master).
- [ ] Draft PR with `## Knowledge`; triage; `## Review triage`.

## PR 1b: R2 backend

- [ ] [AC1] Each root `backend "s3" { key = "<dir>/terraform.tfstate" }`, `required_version >= 1.10`.
- [ ] [AC2] `backend.s3.tfbackend` generated from `terraform.state` in `common.yaml`, drift test.
- [ ] [AC4] Runner: backend credentials in the child env, `init -reconfigure -backend-config`, refusal list for unrecovered roots (TF-015).
- [ ] [AC4] Read-only `show` and `state list|show` runner actions (`make tf-state-list ROOT=`), so the runbooks' state reads keep working once the backend credentials leave the shell; `dns-terraform.md` and `infra/terraform/README.md` point at them.
- [ ] Live, first: re-run `make tf-dns-plan` from msi on this branch's base (the `vps_ip` render from PR 1a) before any state moves.
- [ ] [AC9] `aws` provider takes the IAM pair from SOPS; `aws.*` and `terraform.state.*` in `SECRET_CATALOG` (#1351).
- [ ] [AC5][AC6] `make tf-state-bootstrap`: bucket, history lock, scoped token proven by consequence; second run unchanged.
- [ ] [AC8] Snapshot to `history/<root>/<lineage>/<serial>.tfstate` after every state write; repeat is a no-op.
- [ ] [AC7] `make tf-state-migrate ROOT=`: count before/after, first snapshot, local file kept.
- [ ] `make test-tfstate-lock-live` from the conditional-write probe.
- [ ] [AC10] ADR-069, `docs/runbooks/terraform-state.md`, lesson-564, CLAUDE.md gotcha.
- [ ] Live: bootstrap, migrate `dns`, `r2`, `aws` on msi, `No changes` from the Mac (operator confirms each write).
