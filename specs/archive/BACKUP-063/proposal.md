---
id: "BACKUP-063"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-09-30"
issue: "mlorentedev/kubelab#1954"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-063: the weekly check reads pack data back from R2

## Why

<!-- from issue #1954: BACKUP-063: the weekly restic check never reads pack data back from R2 -->

The weekly unit runs a bare `restic check` (`node-backup-ship.sh.j2`, `RUN_CHECK=1`). That checks the repository's structure and never downloads a pack. A corrupted or truncated pack in R2 is found by the restore that needs it, which is the worst time to find it. Epic #1923 lists "weekly `restic check --read-data-subset`" under "Keep proving them", and this spec delivers that line.

## What

1. **A rotating subset.** The weekly check runs `check --read-data-subset n/t`, where `t` is declared once in the role defaults and `n` is derived from the week at run time. Every pack is then read at least once every `t` weeks.
   - `n` counts **weeks since the Unix epoch**, not the ISO week the issue proposes. ISO weeks go from 52 or 53 back to 1, so `week mod t` skips or repeats a group at every year boundary, and the "every pack within `t` weeks" guarantee would fail once a year. Epoch weeks are continuous.
   - The script prints the group it reads (`reading pack group n/t`), so the journal records which part of the repository a given week proved.
2. **One knob for read parallelism, used only if a measurement needs it.** `check` reads packs over the backend's connection pool (`s3.connections`, 5 by default). The RPi3 unit runs under `MemoryMax=128M`, and a normal ship there already peaks at 90M. If the subset check exceeds the cap, the answer is fewer connections (`-o s3.connections=N`) on that node, not a larger cap.
3. **Measurement through the tooling.** `make backup-node NODE=<n> ENV=prod INTEGRITY=1` starts the weekly integrity-check unit, not the frequent ship unit, and prints the unit's journal, which includes systemd's `memory peak` line. `CHECK=1` is already taken by Ansible check mode, hence a separate name. This is how AC2 is measured, and how the next change to the check will be measured.
4. **A read failure pages.** This behaviour already exists (`set -e`, then `OnFailure=kubelab-notify@%n`); a test now pins it.

## Out of scope

- Any change to the frequent ship unit, the schedule, or retention.
- A restore test (#489). This spec proves the bytes are readable, not that a restore works.
- The per-node buckets (BACKUP-057). This spec lands first, and BACKUP-057 PR 4 rebases onto it; both touch `node-backup-ship.sh.j2`.

## Risks / open questions

- **The 600s budget is shared.** The weekly unit runs `backup`, `forget --prune` and `check` under one `TimeoutStartSec=600`. `t` must fit what is left after the other two on the slowest node, so the measurement times the whole unit, not the check alone.
- **Choice of `t`.** It is fixed after measurement: the smallest `t` (the most coverage per week) that fits the memory cap and the time budget on every node. If the repositories are small enough, that could be `t = 1`, a full read every week. The measured numbers are recorded in `verification.md`.
- **Cost.** R2 egress is free. Each pack read is one class B operation, and there are 10M free per month. At 16 MiB per pack, even a full weekly read of a 10 GB fleet is about 640 operations a week. The measured pack counts are recorded to back this up.

## Acceptance criteria

- [ ] **AC1**: The weekly check reads a rotating subset `n/t`, with `n` derived from epoch weeks. A test drives the script's clock across `t` consecutive weeks and asserts that every group `1..t` is read exactly once. It also asserts that `n` stays continuous across a year boundary.
- [ ] **AC2**: On every node in `backup.sources`, the weekly unit with the chosen `t` completes within `TimeoutStartSec` and, on the RPi3, under `MemoryMax`. Each node's duration and `memory peak` are measured with `make backup-node ... INTEGRITY=1` and recorded in `verification.md`.
- [ ] **AC3**: A `check` failure exits the script non-zero, so the unit fails and `OnFailure` pages. A test pins it with a fake restic whose `check` fails.

## References

- Issue: mlorentedev/kubelab#1954. Epic: #1923.
- Related: #1955 (BACKUP-057, which rebases onto this), `specs/archive/BACKUP-044-critical-subset-pipeline/verification.md` (memory measurements on the RPi3).
