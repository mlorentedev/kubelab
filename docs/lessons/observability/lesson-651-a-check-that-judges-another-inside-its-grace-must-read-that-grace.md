---
id: lesson-651-a-check-that-judges-another-inside-its-grace-must-read-that-grace
type: lesson
status: active
created: "2026-10-29"
owner: manu
category: observability
tags: [kubelab, observability, edge, systemd]
---

# A check that judges another check inside its grace must read that grace

**Context**: NET-005's hard-reset test T3 boots the edge without its uplink adapter and runs `make edge-boot-check CASE=no-uplink`. The case passes when `kubelab-edge-liveness.service` has failed on the missing uplink.

**Problem**: The liveness check tolerates a missing uplink for `EDGE_LIVENESS_GRACE` misses in a row, a minute apart, and its timer first runs 5 minutes after boot. So it fails about 7 minutes in, by design. The boot check read only whether the unit had failed. Run earlier, it reported FAIL for an edge doing what it was built to do, and T3 was judged too early twice before it passed (#2774). The runbook said to wait 10 minutes, but a wait that lives only in prose is skipped exactly when the operator is in a hurry.

**Solution**: When the unit has not failed, the boot check reads the misses the liveness check counted (`/run/kubelab-edge-liveness/uplink.misses`), the grace from the unit's own `Environment=`, and, before the first run, the timer's next elapse in microseconds since boot (`busctl get-property ... NextElapseUSecMonotonic`, since `systemctl show` prints it as a formatted timespan). Inside the grace it prints `WAIT` with the minutes left and exits 2. A grace it cannot read, a count past the grace, or a run that never ended still fails. `tests/test_edge_boot_check.py` holds the pending case and that the values are read from what the role deploys.

**Rule**: A check that judges another component's verdict inherits that component's grace. Read the grace and the progress through it from the component's deployed state, and report "not yet, N minutes" as its own outcome, distinct from pass and from fail. Never infer it, and never let it turn a real failure elsewhere into a wait.

**Tags**: `#net-005` `#systemd` `#edge` `#issue-2774`
