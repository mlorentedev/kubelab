---
id: lesson-505-four-copies-of-one-phase-drift-in-their-guards
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, drills, refactoring, complexity]
---

# Four copies of one phase drift in their guards

**Context**: Four restore drills (Postgres, Headscale, Gitea, and Authelia with
n8n) were written one after another, each by copying the last one's shape:
choose the newest restic snapshot, restore it into a scratch directory, start a
scratch container, compare with live, tear both down (#2015).

**Problem**: The copies drifted, and each drift was in a guard, where nothing
fails until the input that exercises it arrives:

- Gitea and the app drill reported a malformed `restic snapshots --json` as
  CANNOT CHECK. Headscale and Postgres called `json.loads` unguarded and raised.
- Three drills took `snapshots[-1]`, Postgres took `snapshots[0]`. With one
  capture group they agree. With two they would restore different snapshots.
- Three drills failed when the scratch directory survived its deletion.
  Postgres never checked, though the directory holds a full dump of the cluster.

No test caught any of it, because each drill's tests exercised only the guards
that drill had. Two independent reviews found pieces of it by reading. The
four drill functions were also at cyclomatic complexity 12 to 15, and nothing
measured that either.

**Solution**: One module, `toolkit/features/restore_drill.py`, owns the shared
phases: `latest_snapshot` (every unreadable shape is CANNOT CHECK, and two
capture groups are CANNOT CHECK rather than a choice by position),
`restore_source`, `wait_until`, `report`, and the `scratch` context manager,
which always removes the container and the directory and sets `box.clean`.
Each drill keeps only what is its own: the live read, the comparison and the
proof. Ruff's `C901` at 10 now binds `toolkit/features/*drill*.py` through a
negated per-file ignore, so the bar cannot be lost again without CI failing.

**Why**: A copied phase is a fork with no merge. Fixing a guard in one copy
makes the others look complete, because they still read as the same code.
Before writing a second instance of a phase, extract it. A shared phase gets
one set of guards and one set of tests, and every caller inherits both.
