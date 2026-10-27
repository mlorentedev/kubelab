---
id: lesson-641-a-boot-order-read-from-the-journal-fails-once-its-size-cap-drops-the-boots-first-seconds
type: lesson
status: active
created: "2026-10-27"
owner: manu
category: observability
tags: [kubelab, observability, systemd, journald, edge]
---

# A boot order read from the journal fails once its size cap drops the boot's first seconds

**Context**: The lab edge's boot check (NET-005 AC13) asserts that the uplink's
drops are loaded before the uplink can have an address (AC3). Its first version
read the order from the journal: the first `nftables.service` message of the
boot against the uplink's first carrier message.

**Problem**: Run read-only against the real RPi4, it failed. The drops had in
fact loaded first, but `journalctl -b` started at 27.96 s: journald runs with
`Storage=persistent` and `SystemMaxUse=20M`, the cap was full (19.1M), and
rotation had already dropped the boot's first seconds. Every fake in the test
suite kept the whole journal, so 46 tests passed against a source the real host
did not have. A check that reads the journal for early boot depends on a
retention setting nobody set for it, and fails the day the log grows.

**Solution**: Read systemd's own record of the boot instead. Every unit keeps
its transitions in microseconds since boot, whatever the journal holds:

```sh
systemctl show -p ActiveEnterTimestampMonotonic --value nftables.service        # 9.61 s
systemctl show -p InactiveExitTimestampMonotonic --value systemd-networkd.service # 15.54 s
```

The uplink gets no address before networkd configures it, because the role
disables IPv6 on it when the device appears. So "ruleset active before networkd
started" is the order AC3 needs, read from a source no cap can rotate away.

**Rule**: For an order between units in the current boot, read the units'
monotonic timestamps, not the journal. The journal is history with a size limit,
and early boot is the first thing it drops. A reload moves the timestamp too, so
the check is for a boot nothing has touched since.

**Tags**: `#systemd` `#journald` `#boot-order` `#net-005`
