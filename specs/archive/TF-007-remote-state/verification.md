---
tags: [spec, verification, templates]
created: "2026-10-13"
---

# Verification - TF-007-remote-state

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

PR 1a covers AC3 and AC4; the rest land with PR 1b.

- [x] AC3 -> `tests/test_terraform_single_entry.py` (Makefile recipes, toolkit AST scan, one `$(_TF)` line per target). Mutation: a raw `terraform plan` in `tf-dns-plan` goes red.
- [x] AC4 -> `tests/test_terraform_runner.py`, `tests/test_terraform_plan_guard.py`, `tests/test_vps_firewall_tfvars.py`. Mutations: legacy renders kept, inherited `TF_VAR_*` kept, guard ignored, tfvars 0644, `--allow-destroy` hardwired on dns: all red.
- [x] AC4 live -> msi, 2026-10-13: `make tf-dns-plan` and `make tf-r2-plan` read `No changes` with exit 0 on master `1b900c22` and on this branch `1fc2ddba`.
- [x] AC1, AC2 -> `tests/test_terraform_backend.py` (each root's backend block, `>= 1.10`, the committed file equals the render, no credential, no `encrypt`).
- [x] AC5, AC6 live -> Mac, 2026-10-13: `make tf-state-bootstrap` logged `bucket kubelab-tfstate: created`, `lock rule terraform-state-history on history/: set`, `token kubelab-tfstate: minted` (the consequence check inside: lists the state bucket, refused on `kubelab-backups`); rc 0. Second run: `kept` x3, rc 0. The SOPS diff by key name adds `terraform.state.{access_key_id,secret_access_key}` and nothing else. Unit tests: `tests/test_terraform_state_bootstrap.py`.
- [x] AC8 -> `tests/test_terraform_runner.py` history section (before/after copies, create-only put, a failed copy before a write stops it, a taken key is a no-op, whether R2 answers `PreconditionFailed` or `ObjectLockedByBucketPolicy`; serial 0 is never copied). Live: `make tf-state-history ROOT=dns` lists `history/dns//0.tfstate` (the empty serial-0 answer, copied before that skip existed; locked until 2027-10-14) and `history/dns/6b5c1454-…/1.tfstate`.
- [x] AC9 -> `SECRET_CATALOG` entries; `test_every_secret_a_run_requires_exists_in_sops` green once the bootstrap wrote the pair. `make secrets-audit`: 100% in dev, staging and prod; it still exits non-zero on an orphan that master has too (SEC-031 #2240).
- [x] AC10 -> ADR-069, `docs/runbooks/terraform-state.md`, lesson-564.
- [x] Mutation: 18 mutations on the runner (local-state guard, unrecovered guard, create-only put, history env, migrate gate x2, `-reconfigure`, apply-only secrets, snapshots before/after, restore serial bump, restore lineage and content checks, restore arrival, 0600 download, `force-unlock -force`, restore ref), all RED against a green baseline. Later: migrate content gate (7), `-auto-approve` passthrough (2, on #2236), locked-key-as-copy (1), persisted state and pre-remote source (5), all RED.
- [x] AC7 live -> msi, 2026-10-13/14, on `d3390f8c`..`25c9a18f`. Every file's checksum is unchanged after its rename to `terraform.pre-remote.tfstate`.
  - `dns` (14 resources, local lineage `7c725817`, serial 113): the first push landed under a lineage minted for it, `6b5c1454`, at serial 1. The lineage gate refused it (lesson-566). After the content gate, the re-run found the content in R2 and renamed without a second push.
  - `r2` (2 resources): landed at `178d684d`, serial 1, copied to history.
  - `aws` (0 resources, 0 outputs): the first run took the empty key as already holding it and renamed without a push. After the persisted-state fix, the re-run pushed from the `.pre-remote` copy: `e8e59ae6`, serial 1, copied to history.
  - A second `make tf-state-migrate` on each root logs `already migrated`.
  - Mac: `make tf-dns-plan` and `make tf-r2-plan` read `No changes`. `make tf-state-list ROOT=aws` exits 0 with no addresses. `make tf-aws-plan` stops at STS `InvalidClientTokenId`, a credential problem, not a state one. The SOPS `aws` pair is the `kubelab` profile's key, which master's plan already used, and `kubelab-terraform` has no access key (#1351).
  - `make test-tfstate-lock-live`: 1 passed (8 concurrent writers x 10, one winner each).

## Adversarial review

`review.md`: verdict PASS on `e61f2320`, reviewer `nan/mimo-v2.6-flash`. Seven Minor findings, each disposed:

1. `make secrets-audit` exits 1. The cause is an orphan this spec did not add. AC9's own keys all resolve (f9: 8 secrets). Ticketed as SEC-031 #2240.
2. The `tasks.md` triage box is unticked. This is by design: it is ticked once `## Review triage` is posted on #2239.
3. The `proposal.md` AC boxes were unticked. Ticked; the evidence for each is in the list above.
4. The proposal's shorthand omits `ROOT=` on `tf-state-restore`/`tf-state-unlock`. Declined: `proposal.md` is frozen after review, and the runbook, which operators use, carries `ROOT=`.
5. Three full-suite failures on macOS: Colima does not share `/private/var/folders`, so a `tmp_path` bind mount arrives empty. They are pre-existing on master and in files this spec does not touch. Ticketed as TOOL-113 #2244.
6. `_restore` reads `current["serial"]` by key. Ticketed as TF-019 #2245, so the reviewed code stays the code that archives.
7. Five functions exceed 40 lines, with C901 ≤ 10 held. Ticketed as TF-019 #2245.

## Test status

- Test suite: `poetry run pytest tests/test_terraform_*.py` -> all green (178 in the runner file alone).
- Manual smoke test: the live AC5/AC6/AC7 runs above, from the Mac and from msi.
- No regressions in existing test suite: yes. `make test-fast` on macOS fails only in the five files master fails on macOS (#2237); none is touched here.

## Decisions made during implementation

- PR 1 was split into 1a (runner, local backend kept) and 1b (R2 backend), so the refactor is proven on the state it already has before the state moves.
- `aws1-replace` moved from `-auto-approve` to the guarded apply with an explicit `--allow aws_instance.argo_hub`.
- `compute` is registered (`make tf-compute-plan|apply`), after review of #2236: an unregistered root could only be run by hand, around the secret handling. It stays DR-only; its deployer key is TF-018.
- The DNS root's `vps_ip` is rendered from `networking.vps.public_ip` rather than typed into `dns.tfvars` a second time. The two values were equal (162.55.57.175), so the live plan is unchanged by construction.
- The child environment is an allowlist: every inherited `TF_*` is dropped except the plugin cache (lesson-563).
- `gcp-killswitch-prove` tears down after a failed apply too, and fails when the teardown fails.
- A `terraform fmt` pre-commit hook was added because `compute/main.tf` had drifted unnoticed; the CI gate is TF-016.

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/storage-backup/lesson-566-terraform-does-not-keep-a-states-lineage-across-a-migration.md (also lesson-564, lesson-563)
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? yes: docs/adr/adr-069-terraform-remote-state-on-r2.md
- [x] New pattern candidate for `00_meta/patterns/`? no: one project uses Terraform remote state; the transferable rule (verify a move by content, not identifiers) is in lesson-566 and recurs nowhere else yet

## Archive checklist

- [x] `proposal.md` frontmatter set to `status: archived`
- [x] Folder moved: `specs/TF-007-remote-state/` -> `specs/archive/TF-007-remote-state/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] Promotions above executed (if any)
