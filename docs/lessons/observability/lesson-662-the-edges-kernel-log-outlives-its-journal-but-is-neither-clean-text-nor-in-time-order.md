---
id: lesson-662-the-edges-kernel-log-outlives-its-journal-but-is-neither-clean-text-nor-in-time-order
type: lesson
status: active
created: "2026-10-30"
owner: manu
category: observability
tags: [kubelab, observability, rsyslog, journald, rpi4, edge]
---

# The edge's kernel log outlives its journal, but is neither clean text nor in time order

**Context**: Reading NET-005 B12, a 48-hour soak in which the uplink adapter's driver must not reset (#2807). The journal holds about 8 hours on the RPi4 under its 20M cap (#2702), so a kernel-log check at hour 48 would only see the last 8.

**Problem**: rsyslog is active on the edge and writes every kernel line to `/var/log/kern.log`, which it keeps for weeks, so the history was never lost. Read naively it is still wrong, in two ways that both look clean:

- The hard-reset test's power cuts left runs of NUL bytes in the file. `grep` then answers `binary file matches` and prints no line, so a soak with resets in it reads as one with none.
- The RPi4 has no clock that survives power-off. A boot's first lines carry the time saved before the cut, which after a power cut was 4.5 hours early. A previous boot's last lines are stamped after the next boot's banner, so a window chosen by timestamp mixes two boots.

**Solution**: `make edge-soak` reads `kern.log*` over the LAN, oldest file first, with the NULs dropped and `grep -a`. It takes the current boot as everything after the last kernel banner in write order, never by time, and measures its length with `/proc/uptime`. It fails closed: with no banner, or an rsyslog that did not start with this boot, it says it cannot tell. `tests/test_edge_soak.py` runs the pipeline on files with NULs and a gzipped rotation, and holds a previous boot whose lines are stamped after the current banner.

**Rule**: On a host without a real-time clock, order log lines by where they were written, not by their timestamps, and measure durations with the monotonic clock. Read a log file that a power cut can reach with NULs stripped and `grep -a`, or a missed match reads as a clean result. See also lesson-641: a journal's size cap drops a boot's first seconds.

**Tags**: `#rsyslog` `#journald` `#edge` `#pr-2811`
