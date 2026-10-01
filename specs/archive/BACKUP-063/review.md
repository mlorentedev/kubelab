---
spec: "BACKUP-063"
verdict: "PASS"
reviewed_sha: "1b910c1e584633bdb6d55aba29261e7090f360d6"
reviewer: "agy/gemini-3.1-pro-high"
date: "2026-10-01"
---
## Adversarial review

**Scope**: BACKUP-063
**Sources**: `specs/BACKUP-063/{proposal,tasks,verification}.md`, PR diff `fbf4883f41abf02ee1e18da2eac5638c89e835fc...HEAD`

### Spec and task alignment
- **AC1** (rotating subset n/t with epoch weeks): Implemented exactly. Epoch weeks prevent year-boundary skips. `node_backup_check_read_data_groups` handles `t`. Tests verify rotation over consecutive weeks and across 2027-01-01.
- **AC2** (prod measurement and parallelism knob): `t=1` was chosen based on production measurement (15x headroom). Since `MemoryMax` cap was not reached (peaked at 83M / 128M cap), the `s3.connections` knob was correctly omitted per the spec ("used only if a measurement needs it"). `make backup-node INTEGRITY=1` invokes the correct check unit.
- **AC3** (check failure pages): Script uses `set -e`, failing immediately on restic non-zero exit, triggering systemd `OnFailure`. Pinned by `test_a_failed_check_fails_the_run`.

### Findings

| Severity | Reality | Area | Finding | Evidence | Test (named, or UNTESTED) | Fix location (code / tests / spec / vault) |
|----------|---------|------|---------|----------|---------------------------|---------------------------------------------|

*(No Blocker, Major, or Minor findings. Implementation is robust against timezone/DST shifts, handles modulo correctly, relies on `set -e` for proper systemd failing, and cleanly achieves the spec without scope creep.)*

### Evaluator rubric

| Dimension | Grade (A-D) | Rationale (one line) |
|-----------|-------------|----------------------|
| Correctness        | A | Epoch math ensures continuous rotation independent of DST; test suite proves boundary conditions and subset mapping. |
| Verification       | A | Reproducible commands used in production to measure both duration and peak memory explicitly. |
| Scope              | A | Diff strictly matches proposal; parallelism knob omitted appropriately based on verification data. |
| Reliability        | A | Timezone/DST shifts cannot jump epoch weeks; restic `check` failures correctly fail the systemd unit. |
| Maintainability    | A | Logic is simple and clearly commented; test cases comprehensively document the intended bounds and logic. |
| Handoff-readiness  | A | Verification filled with clear baseline vs candidate metrics; no spec drift. |

### Verdict
PASS

### Recommended next steps
- Proceed with `dotf spec archive`. The implementation is exemplary, verified, and advisable to archive in its current state.
