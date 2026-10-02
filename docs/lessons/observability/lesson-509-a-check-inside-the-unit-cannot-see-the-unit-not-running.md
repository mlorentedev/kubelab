---
id: lesson-509-a-check-inside-the-unit-cannot-see-the-unit-not-running
type: lesson
status: active
created: "2026-10-02"
owner: manu
category: observability
tags: [kubelab, observability, backup, alerting, loki]
---

# A check inside the unit it guards cannot see the unit not running, and filtering on "is it up" turns "all off" into a page

**Context**: BACKUP-032 (#485). The on-demand nodes (beelink, rpi4) ship to R2
hourly while they are up. A ship that *fails* pages through
`OnFailure=kubelab-notify@%n`. A ship that never *starts* (a disabled timer, a
unit that never runs) is seen only by the node's Uptime Kuma push heartbeat,
and that heartbeat is muted for the `on-demand` tag because the node is off most
of the week.

**Problem**: Two traps, one on each side of the obvious fix.

1. The failure hook lives inside the unit it guards. When the unit does not run,
   neither does the hook, so "never started" was nobody's page.
2. The obvious freshness rule filters to nodes that are up:
   `... | reachable="1" | unwrap snapshot_age_seconds`. With the homelab off,
   the common case, that filter matches nothing, the query returns no data, and
   `noDataState: Alerting` pages, every night, for the state the rule exists to
   ignore.

**Solution**: Judge from outside the unit, from the destination: the in-cluster
R2 watcher reads each node's newest snapshot and also knocks on the node's
tailnet address (`nc -z`). The rule never filters on `reachable`; it multiplies:

```logql
last_over_time(... | class=`on-demand` | unwrap snapshot_age_seconds [7h]) by (node)
*
last_over_time(... | class=`on-demand` | unwrap reachable [7h]) by (node)
```

An off node is a series whose value is 0, never a missing series. `for: 7h`,
longer than the 6 h probe interval, makes two consecutive probes agree. The
reachability signal is checked by a positive control: an always-on node the
probe cannot reach fails the probe's health, because otherwise a broken probe
would read every on-demand node as "off" forever. A test evaluates the rule in
a real Loki, against lines printed by the real probe
(`tests/test_r2_backup_freshness_rule.py`).

**Rule**: A liveness check belongs outside the thing it watches. In an alert,
express "only while X" as a product with X, never as a filter on X: a filter
that can match nothing turns the normal case into "no data". And give every
"cannot reach" signal a positive control that is never expected to be off.

**Tags**: `#backup` `#alerting` `#loki` `#nodata` `#485`
