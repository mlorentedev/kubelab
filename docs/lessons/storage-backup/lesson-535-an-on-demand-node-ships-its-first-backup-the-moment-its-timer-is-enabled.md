---
id: lesson-535-an-on-demand-node-ships-its-first-backup-the-moment-its-timer-is-enabled
type: lesson
status: active
created: "2026-10-07"
owner: manu
category: storage-backup
tags: [kubelab, storage-backup, systemd, restic, r2]
---

# An on-demand node ships its first backup the moment its timer is enabled

**Context**: adding ace2 to `backup.sources`, born in its own bucket (spec AI-009
AC7). The bucket has an Object Lock rule: nothing written under `data/` or
`snapshots/` can be deleted for 30 days. The plan was to deploy with
`make backup NODE=ace2`, run the capture alone, inspect the staged tree, and
only then ship, because a wrong first ship stays in the bucket for 30 days.

**Problem**: the ship ran within seconds of the deploy, before the capture could be
inspected. On an on-demand node the timer is `OnBootSec=` plus
`OnUnitActiveSec=`, with no calendar. systemd evaluates `OnBootSec=` against the
boot time when the timer is first started; the node had been up for hours, so
the deadline was already past and the timer fired at once. The deploy is the
first ship; there is no window between them. (An always-on node is different:
`OnCalendar=` with `Persistent=true` and no stamp file waits for the next
calendar slot.)

**Solution**: the staged tree was inspected right after the fact, and it held what the
tests say it should: 8 database snapshots, no `-wal` or `-shm`, the excluded
`bin` and `home/.cache` absent, 6.3 MB. Snapshot `30cd1e8f`, repository
`95c25ab7…`. It was right because the capture's behaviour is covered by tests
that execute the rendered script (#2113, #2114), not because there was a gate.

**Rule**: for a new on-demand node, treat `make backup NODE=<node>` as the first
ship. Check the content before it, with the capture tests and the rendered
declaration, not after it. Do not plan a gate between deploy and ship that the
timer will not wait for.

**Tags**: `#systemd` `#node-backup` `#object-lock` `#ai-009`
