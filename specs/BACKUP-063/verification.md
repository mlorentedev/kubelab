---
tags: [spec, verification]
created: "2026-09-30"
---

# Verification - BACKUP-063

## AC1: rotation

`poetry run pytest tests/test_node_backup_ship_script.py --no-cov -q`: 26 passed (25 before review). Each test was run red first, on `6031a42d`, before the implementation:

- `test_the_weekly_check_reads_a_group_of_pack_data` asserts `check --read-data-subset 1/4` and the journal line.
- `test_the_read_data_rotation_reads_every_group_once_per_cycle`: 4 consecutive weeks read `1/4..4/4`, each exactly once.
- `test_the_read_data_rotation_is_continuous_across_a_year_boundary` covers the weeks around 2027-01-01, which falls in ISO week 53 of 2026. Under ISO weeks, `mod 4` gives the steps `[1, 0]`, so a group repeats. Under epoch weeks the steps are `[1, 1]`.
- `test_the_shipped_group_count_renders_a_check_that_runs` (`23d308d0`, from review): the only render that omits the fixture's group count, so it reads the committed default. Mutation: a default of `0` turns it red while the other 25 stay green.

## AC2: measured in prod, 2026-09-30

Method: from this branch, `make backup ENV=prod`, then `make backup-node NODE=all ENV=prod INTEGRITY=1`. That starts `node-backup-ship-check.service`, the real weekly unit, with its cgroup, timeout and `OnFailure`. Duration is `ExecMainExitTimestamp - ExecMainStartTimestamp` and covers the whole unit: capture, backup, `forget --prune` and check. Memory is systemd's `memory peak`, which is reported only where a memory limit applies.

Baseline on `rpi3`, with the plain `check` from master: 11.0s CPU, **76.2M** peak.

With `t = 1` (`--read-data-subset 1/1`, which reads every pack):

| Node | Packs read | Unit duration | CPU | Memory peak |
|---|---|---|---|---|
| beelink | 17 / 17 | 18s | 6.4s | (no MemoryMax) |
| rpi3 | 15 / 15 | 38s | 33.0s | **78.5M** / 83.4M (two runs), cap 128M |
| rpi4 | 15 / 15 | 24s | 17.6s | (no MemoryMax) |
| kubelab-vps | 6 / 6 | 21s | 3.7s | (no MemoryMax) |

All four finished with `Result=success`, `ExecMainStatus=0` and `no errors were found`.

**Decision: `t = 1`.** It is the smallest `t`, and it fits every node with at least 15x headroom on time. The RPi3 peak rose by 2-7M over the plain check, so reading packs does not scale memory with repository size. Time does: the RPi3 read 15 packs in about 15s, so the 600s budget covers about 400 packs before `t` has to rise. The default's comment records this ceiling.

**Cost:** 53 packs a week across the fleet, which is 53 class B operations against a free tier of 10M a month.

## AC3: a read failure pages

`test_a_failed_check_fails_the_run`: the fake `check` exits 1, the script exits non-zero, and `ship complete` is never printed. The unit fails, and `OnFailure=kubelab-notify@%n` pages. That paging path is unchanged and has been measured since BACKUP-044 Part 5.

## Still to do after merge

- [x] Redeploy from master (`make backup ENV=prod`); expect `changed=0` after the first run. ✓ 2026-10-01 15:3xZ, master `5cf69877`: two consecutive runs, `changed=0 failed=0` on `beelink`, `kubelab-vps`, `rpi3` and `rpi4` both times. The first run was already `changed=0` because prod had been running this branch's templates since before #1956 merged.
