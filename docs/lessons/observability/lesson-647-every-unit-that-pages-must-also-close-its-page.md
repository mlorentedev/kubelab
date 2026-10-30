---
id: lesson-647-every-unit-that-pages-must-also-close-its-page
type: lesson
status: active
created: "2026-10-28"
owner: manu
category: observability
tags: [kubelab, observability, systemd, notify]
---

# Every unit that pages must also close its page

**Context**: A unit opts into the fleet's failure page with `OnFailure=kubelab-notify@%n.service` and into its recovery page with `OnSuccess=kubelab-notify-recovered@%n.service`. lesson-594 wired the recovery only on the units that run more often than the hourly reminder, and let the six-hour TTL close the rest.

**Problem**: A later change made a missing recovery a lasting fault, not a cosmetic one. Since #2749 a delivered recovery is the only thing that clears an undelivered page's failed notifier, and #2762 noted that `kubelab-maintenance` and the `node-backup-*` units send none. The hard-reset test of the lab edge (NET-005 B14) found both on `node-backup-ship`: a timer ran it with the uplink gone, its page could not leave, and the failed notifier would have stayed in `systemctl --failed` until a reboot. Six units paged with no recovery. One more, the edge's shaper, could not use the usual line: it is `RemainAfterExit=yes`, and on such a unit `OnSuccess=` fires when the unit stops, not when its start succeeds (#2689).

**Solution**: Every unit that pages declares a recovery. A plain oneshot uses `OnSuccess=`. A `RemainAfterExit=yes` unit uses `ExecStartPost=-/usr/bin/systemctl start --no-block kubelab-notify-recovered@%n.service` as its last start step. `node-backup-shutdown` is the one exemption, with its reason. Its run ends when it stops, inside the shutdown transaction, and systemd starts no unit there. `tests/test_node_notify_role.py` derives the paging units from the role templates and fails on any unit with neither form. Either form closes the page only on a start that succeeds. While every start fails, the page stays open and an undelivered one leaves its notifier failed: that window is the outage itself, and the first good start closes both. Since #2787 (2026-10-30) an undelivered page is kept in the spool and its notifier no longer fails (lesson-678).

**Rule**: A failure hook and its recovery hook are one contract. Hold every unit that has the first to the second with a test, rather than having each unit opt in. Pick the form from when the unit's work ends: `OnSuccess=` fires on the transition to inactive, so on a unit that stays active it means "stopped", not "succeeded".

**Tags**: `#systemd` `#notify` `#net-015` `#pr-2768`
