---
id: lesson-729-a-pipe-into-grep-q-under-pipefail-can-read-a-match-as-a-miss
type: lesson
status: active
created: "2026-11-09"
owner: manu
category: ansible-provisioning
tags: [kubelab, ansible-provisioning, shell, node-maintenance, flaky-test]
---

# A pipe into `grep -q` under `pipefail` can read a match as a miss

**Context**: `test_the_maintenance_timer_finds_them_held_and_leaves_them_held`
failed once in a CI shard and passed on the rerun of the same tree (#3185). It
runs the maintenance timer's hold block against stubbed `apt-mark`.

**Problem**: The block asked `printf '%s\n' "$HELD_BEFORE" | grep -qx pkg`
under `set -euo pipefail`. `grep -q` exits at its first match; bash's `printf`
writes into a pipe line by line, so when the match is not the last line it can
get SIGPIPE on the next write and exit 141, and `pipefail` makes that the
pipeline's status. The timer then read a held package as unheld, recorded the
hold as its own and released it after its run. The flaky test was a real
defect: on a loaded node the timer could undo the provision's hold on the
Beelink's CI engine. It does not reproduce on macOS; on ubuntu:24.04 with eight
loops in parallel the rendered block misread 13 times in 3200 runs.

**Solution**: Let grep read all of its input (`grep -xF pkg >/dev/null`): 0 in
3200 under the same load. The same form was in `node-backup-capture` and four
Makefile recipes (`.SHELLFLAGS` sets pipefail). `tests/test_pipefail_grep_quiet.py`
fails on any pipe into a quiet grep in a shipped file that sets pipefail, and
shows the mechanism with a producer that writes after the match. The three
workflow sites are #3227.

**Rule**: Under `pipefail`, never pipe into `grep -q`; redirect grep's output
instead. A flaky test that drives real shell is evidence about that shell, so
reproduce it on the target OS under load before treating it as test noise.

**Tags**: `#shell` `#pipefail` `#issue-3185` `#issue-3227`
