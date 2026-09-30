---
tags: [spec, tasks]
created: "2026-09-30"
---

# Tasks - BACKUP-063

> TDD order. `[P]` = no dependency on another unchecked task. `[AC<n>]` = serves acceptance criterion n.

## Setup

- [x] Branch `feat/backup-063-read-data-subset`, worktree `~/Projects/kubelab-backup-063-wt`
- [x] `proposal.md` complete; no open question blocks code (`t` is chosen by measurement, AC2)

## Implementation

- [ ] [P] [AC1] Failing test in `tests/test_node_backup_ship_script.py`:
  - a fake `date` on PATH fixes the clock;
  - with `RUN_CHECK`, restic is called with `check --read-data-subset n/t`;
  - `t` consecutive weeks cover `1..t` exactly once, and a year boundary does not break the sequence.

  Expected: FAIL, because `check` has no subset.
- [ ] [AC1] `defaults/main.yml`: `node_backup_check_read_data_groups` (`t`), with the epoch-week comment. `node-backup-ship.sh.j2`: derive `n`, print the group, run the subset. Expected: PASS.
- [ ] [P] [AC3] Test: the fake `check` exits 1, and the script exits non-zero before `ship complete`. Expected: PASS already (`set -e`); this pins it.
- [ ] [AC2] `backup-node.yml` and `make backup-node`: `INTEGRITY=1` selects `node_backup_ship_check_service_name`. `tests/test_make_backup_node.py`, or the nearest existing Makefile test, asserts that the flag reaches the playbook.
- [ ] [AC2] Deploy to prod from this branch, then run `make backup-node NODE=<n> ENV=prod INTEGRITY=1` on each node:
  - first on `rpi3` with the plain check, as the baseline;
  - then with the candidate `t`.

  Record the duration, `memory peak` and pack count per node in `verification.md`. If the RPi3 exceeds its cap, add `node_backup_check_connections` for that node only and measure again.
- [ ] [AC2] Fix `t` to the smallest value that fits every node, and redeploy from master after merge (`changed=0` on re-run).

## Closing

- [ ] `make test` green; `features.json` verifications non-vacuous
- [ ] `verification.md` filled; independent `dotf spec review`; archive PR closes #1954
