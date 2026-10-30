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

**Problem**: `grep -q` exits at its first match and closes the pipe. Any write the writer makes after that takes SIGPIPE, and `pipefail` reports the writer's 141 as the pipe's status. So the test failed exactly when it had found the name, and only for names early in a large index. Whether the writer is still writing is a race: it wins when it can put the rest into the pipe before grep exits. Past twice the pipe buffer (2 x 64 KiB on Linux) it always loses, because grep reads at most one buffer and the writer can refill only one more. The race is why the hook failed intermittently, and why a size alone does not make a writer safe: one that writes twice, with a pause between, fails on a few bytes.

**Solution**: The name is tested against a here-string, `grep -qxF -- "$name" <<< "$targets"`, so no writer can be cut off. `tests/test_check_lessons.py` builds a 600-lesson index whose targets pass twice the pipe buffer, so the old line fails every run, and asserts the script passes. A second test refuses, in any `scripts/*.sh` that sets `pipefail`, a pipe into a reader that stops early (`grep -q`, `grep -m`, `head`), since those scripts read inputs that grow with the repository.

**Rule**: Under `pipefail`, never pipe into `grep -q`, `grep -m` or `head` from a writer that may still be writing when the reader exits: a large one, or one that writes more than once. Give the reader a here-string or a file.

**Tags**: `#bash` `#pre-commit` `#issue-2765`
