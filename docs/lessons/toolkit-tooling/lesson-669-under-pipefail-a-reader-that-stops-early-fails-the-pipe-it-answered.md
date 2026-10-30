---
id: lesson-669-under-pipefail-a-reader-that-stops-early-fails-the-pipe-it-answered
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: toolkit-tooling
tags: [kubelab, toolkit-tooling, bash, pre-commit]
---

# Under `pipefail`, a reader that stops early fails the pipe it answered

**Context**: `scripts/check-lessons.sh` checks that every lesson file is listed in its category's index. It tested each name with `printf '%s\n' "$targets" | grep -qxF -- "$name"`, under `set -euo pipefail`. With 663 lessons the targets of the busiest index passed 64 KiB, and the hook began reporting lessons that were plainly in the index as missing, intermittently (#2765).

**Problem**: `grep -q` exits at its first match and closes the pipe. When the writer has more to send than the pipe buffer holds, its next write takes SIGPIPE, and `pipefail` reports the writer's 141 as the pipe's status. So the test failed exactly when it had found the name, and only for names early in a large index. Small indexes fit the buffer in one write and never show it.

**Solution**: The name is tested against a here-string, `grep -qxF -- "$name" <<< "$targets"`, so no writer can be cut off. `tests/test_check_lessons.py` builds a 600-lesson index past 64 KiB and asserts the script passes. A second test refuses, in any `scripts/*.sh` that sets `pipefail`, a pipe into a reader that stops early (`grep -q`, `grep -m`, `head`), since those scripts read inputs that grow with the repository.

**Rule**: Under `pipefail`, never pipe a writer whose size you do not bound into `grep -q`, `grep -m` or `head`. Give the reader a here-string or a file.

**Tags**: `#bash` `#pre-commit` `#issue-2765`
