---
spec: "BACKUP-057"
verdict: "PASS-WITH-GAPS"
reviewed_sha: "dd258e775513f675ebe9bfac01b24cb6bced5531"
reviewer: "agy/gemini-3.8-flash-high"
date: "2026-11-14"
---

## Adversarial review

**Scope**: BACKUP-057 (one bucket per node, and a lock no node can lift)
**Sources**: `specs/BACKUP-057/{proposal,tasks,verification,features}.md`, `git diff 2abcecc64e466c0a5c69e59b43e256c8b286e308...HEAD` (31 spec-specific commits)

### Spec and task alignment

The change implements the architectural shift decided in #1920: moving from a single shared R2 bucket (`kubelab-backups`) with shared credentials to dedicated per-node buckets (`kubelab-backup-<node>`), each locked via Cloudflare R2 bucket lock policies that nodes cannot alter.

- **AC1 (Node Isolation)**: Implemented. Nodes in `backup.sources` receive isolated buckets, individual Object Read & Write API tokens scoped strictly to their respective bucket (`bnc.token_request`), and unique 48-byte restic passwords (`backup.nodes.<node>.restic_password`). Verified in unit tests (`test_backup_per_node_isolation.py`, `test_backup_node_credentials.py`) and proven live in prod where `make backup-isolation-probe` confirmed 40 of 40 cross-node list and delete requests refused with `AccessDenied`.
- **AC2 (Bucket Lock & Immutability)**: Implemented. `infra/terraform/r2/main.tf` defines `cloudflare_r2_bucket_lock` rules covering `data/`, `snapshots/`, `keys/`, and `config`, while explicitly excluding `locks/` and `index/`. Policy enforces R (30d) < `--keep-within 31d` and pins `--max-repack-size 0` in retention flags to prevent pack timestamp rewrites. Tested in `test_r2_terraform.py` (35 passing tests). Free-tier storage alert rule (`r2-backup-size`) configured and verified (`test_r2_backup_alerting_rules.py`).
- **AC3 (Prune Reliability & Immutability Under Lock)**: Implemented. `forget --prune` was decoupled from the shipping unit into an independent daily systemd timer (`node-backup-prune.service` / `.timer`), preventing R2 lock refusal retry delays (up to 15 min per pack) from timing out regular backup ships. Stale locks are cleared via `restic unlock` before runs. The copied history race condition (where `restic copy` preserved snapshot metadata timestamps while R2 aged objects from upload time, documented in lesson-628) was handled via clearance wait logic. The post-clearance 7-day prune window (2026-11-07 to 2026-11-14) completed with 0 failures across all 5 nodes (`ace2`, `beelink`, `rpi3`, `rpi4`, `kubelab-vps`).
- **AC4 (History Migration & Shared Bucket Decommissioning)**: Implemented. All 192 pre-migration snapshots across 4 nodes (`vps`: 39, `rpi3`: 40, `rpi4`: 52, `beelink`: 61; `ace2` born in own bucket) were copied and verified 1:1 via restic's `original` ID field. Once weekly checks verified integrity, the shared `kubelab-backups` bucket was emptied, deleted, its credentials revoked, and transitional code removed.
- **AC5 (Runbooks & Escrow)**: Implemented. `docs/runbooks/offsite-backup-restore.md` and `docs/runbooks/runbook-disaster-recovery.md` accurately detail the new topology and document uncoverages (admin token, data older than R, and SOPS recipient key). Pinned by `test_offsite_runbook_claims.py` (16 passing tests). `make backup-escrow-check` validates restic passwords against Bitwarden escrow (`test_backup_escrow_check.py`).

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|
| Minor | REAL | spec-artifacts | Template evidence checklist in `verification.md` lines 12–16 remains unpopulated with literal `<hash>` and `<name>` placeholders, despite detailed evidence sections existing below | `specs/BACKUP-057/verification.md:12-16` | UNTESTED (spec inspection) | spec (`verification.md`) |
| Minor | REAL | tasks-state | Task item `make test and lint green` in `tasks.md:148` is unchecked `[ ]`, although `make lint` and the test suites pass cleanly | `specs/BACKUP-057/tasks.md:148` | `make lint`, `poetry run pytest` | spec (`tasks.md`) [contract set: tracked only, do not edit] |
| Minor | REAL | spec-artifacts | Typo in `verification.md:322` citing `lesson-539 in identity-secrets`; the lesson was actually filed under `docs/lessons/storage-backup/` | `docs/lessons/storage-backup/lesson-539-*.md` | UNTESTED (file path inspection) | spec (`verification.md`) |
| Minor | REAL | test-retention | Deletion of `tests/test_backup_migrate.py` (425 LOC) and shared verify tests in PR 5 lacked formal 5-field test retention audit in `verification.md`, though justified by retirement of `kubelab-backups` | Commit `e5a8205bb8eb`, `specs/BACKUP-057/verification.md` | `test_backup_per_node_isolation.py`, `test_backup_isolation_probe.py` | spec (`verification.md`) |
| Minor | REAL | observability | Refused unreferenced pack deletes during prune on `rpi3` (6 packs) and `rpi4` (1 pack) exit 0 and recur nightly for up to R days without structured telemetry | `specs/BACKUP-057/verification.md:264-271`, commit `c4e020dce2e9` | `tests/test_node_backup_prune_script.py` | code (tracked in follow-up issue #3496) |
| Minor | REAL | verification | Systemd journald 20 MB size limit on `rpi3`, `rpi4`, and `beelink` rotated out older prune journals during the 7-day window, requiring reliance on alert sink silence and a manual run | `specs/BACKUP-057/verification.md:254-256` | UNTESTED (operational logs) | ops (tracked in follow-up issue #2702) |

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | All acceptance criteria verified in code and live prod; negative and abuse paths rigorously enforced. |
| Verification       | B | Comprehensive scratch and prod measurements recorded; minor deduction for unpopulated template placeholder lines in `verification.md:12-16`. |
| Scope              | A | Implementation adheres strictly to the 5-phase PR plan; shared bucket safely decommissioned. |
| Reliability        | A | Robust fault isolation: stale lock recovery, failure notification hooks, retry lock timeouts, and separate prune unit. |
| Maintainability    | A | Clean modular toolkit features, low complexity, clear architectural intent, and exhaustive unit tests. |
| Handoff-readiness  | A | Runbooks updated and test-guarded, disaster recovery paths verified, Bitwarden escrow checked, and 9 lessons captured. |

### Verdict
PASS WITH GAPS

### Recommended next steps

The contract set (`proposal.md`, `tasks.md`, `features.json`) is **closed**. Do NOT modify contract files, as doing so would invalidate recorded contract digests and require a full re-review.

1. **In `verification.md` (outside contract set)**:
   - Populate or replace the placeholder `## Evidence` checklist (lines 12–16) with the verified commits and test references.
   - Correct the category path citation for `lesson-539` from `identity-secrets` to `storage-backup` (line 322).
   - Record the test deletion retention entry for `tests/test_backup_migrate.py`.
2. **Follow-up issues (already tracked)**:
   - Track #3496 for structured metrics on recurring refused pack deletes.
   - Track #2702 for edge node journald log retention tuning.
3. **Archive execution**:
   - `dotf spec archive BACKUP-057` is advisable and ready to execute.
