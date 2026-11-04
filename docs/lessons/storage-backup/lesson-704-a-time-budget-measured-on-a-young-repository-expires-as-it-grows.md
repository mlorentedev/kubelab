---
id: lesson-704-a-time-budget-measured-on-a-young-repository-expires-as-it-grows
type: lesson
status: active
created: "2026-11-04"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, restic, r2]
---

# A time budget measured on a young repository expires as the repository grows

**Context**: The weekly `restic check` reads pack data back from R2 (BACKUP-063). `read-data-subset` 1/1, a full read, was chosen on 2026-09-30, when each repository held 6-17 packs and the whole weekly unit took 18-38s of its 600s.

**Problem**: Five weeks later the repositories held 364-961 packs, up to 2.8 GB, and the check timed out on three nodes (#2920). The comment beside the value said to raise it near ~400 packs, but nothing measured the packs, so the first signal was the timeout. Its notice read `failed`, like a damaged repository. Three nodes also started their catch-up check in the same two minutes after a boot, on one uplink.

**Solution**: Read 1/16 of the packs a week, measured on the slowest node and the largest repository (about 300s on rpi4, inside the 600s). Spread the check timer's catch-up over one hour. Title a unit killed by its timeout `timed out`. The budget stays the ship's 600s on purpose: `check` holds the exclusive lock, and ship and prune only wait about that long for it.

**Rule**: A duration budget measured on a store that grows records when it was measured and at what size. Size the work to the budget (a subset, a rotation), not the budget to the work, whenever the work holds a lock that others wait on.

**Tags**: `#restic` `#r2` `#backup`
