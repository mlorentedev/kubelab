---
id: lesson-511-restic-reports-a-refused-pack-delete-as-success
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2, object-lock]
---

# restic reports a refused pack DELETE as success, and how it reports a refused snapshot DELETE depends on its version

**Context**: BACKUP-057 puts R2 bucket lock rules on each node's restic repository. Before any prod bucket got the lock, its scratch measurement (`specs/BACKUP-057/verification.md`) checked what restic does when R2 refuses a DELETE, since the ship has to report a refused prune apart from a failed backup (Q6).

**Problem**: The exit code does not carry the refusal.

- Pack DELETE refused (the unreferenced packs an interrupted backup leaves, the expected case on on-demand nodes): `prune` prints `unable to remove data/... from the repository`, then `done`, and **exits 0**.
- Snapshot DELETE refused: restic 0.19.1 (the fleet's pin) exits 3 with `failed to remove one or more snapshots`. restic 0.18.1 (the workstation's) exits **0** on the identical refusal.

Each refused object also holds restic in its own retry layer for about 15 minutes. `-o s3.retries=0` does not shorten that, because it configures the S3 client and not restic's retries. Concurrent refusals overlap, so three packs took 14:53. The ship unit's `TimeoutStartSec=600` is shorter than one refusal.

**Solution**: The measurements are recorded, and the ship's design is moved to read restic's output as well as its exit code, with a bound around the prune imposed from outside restic. The design itself is BACKUP-057 PR 4, open for the operator.

**Rule**: Measure a tool's failure behaviour with the version production pins, never with whatever is on the workstation: here the two versions disagreed on the exit code. And never infer "a delete was refused" from an exit code alone. Measure it against a real refusal, for each object class, because one tool can report two refusals in two different ways.

**Tags**: `#restic` `#r2` `#object-lock` `#issue-1920`
