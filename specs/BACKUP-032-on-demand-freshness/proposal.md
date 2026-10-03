---
id: "BACKUP-032-on-demand-freshness"
type: spec
status: draft # draft | implementing | verifying | archived
created: "2026-10-01"
issue: "mlorentedev/kubelab#485"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
wip_override: "operator decision 2026-10-02: start BACKUP-032 (epic #1923); the WIP backlog of 27 specs is cleaned up under its own ticket (27 active, limit 10, 2026-10-01)"
---

# BACKUP-032: On-demand backup freshness

## Why

<!-- from issue #485: BACKUP-032: Stale backup detection — alert if any backup repo hasn't been updated in >48h -->

An on-demand node (Beelink, RPi4) can be up and writing while its backup never runs, and nothing reports it. A ship that runs and fails pages through `OnFailure=`. A ship that never *starts* (a disabled or masked timer, a unit that does not load) is seen only by the node's Uptime Kuma push heartbeat (BACKUP-044 AC9), and that monitor is muted for `on-demand` on purpose, because an absolute age rule goes DOWN every time the homelab sleeps (ADR-028). Each signal the issue proposes is computed inside the ship, and a check that lives in the unit it guards cannot see the unit not running (`node-backup-capture.service.j2`: "a different failure and a different control"). The Beelink holds the Gitea forge, so this gap is where a silent loss of the canonical repositories would hide.

## What

- `r2-backup-watcher` adds these fields to each `r2_backup_node` line:
  - `newest_snapshot`: the time of the newest snapshot, ISO 8601 UTC, read with the same `restic snapshots --latest 1` call, for the operator to read.
  - `snapshot_age_seconds`: the age of that snapshot at probe time. It is a measurement, not a verdict, so the probe still judges no age. It exists because LogQL can `unwrap` a number but not a timestamp.
  - Both are `null` when restic cannot answer, never a value that reads as fresh.
  - `class`: the node's ADR-028 class from `targets.txt`. The freshness rule filters on it, so the probe must emit it: a filter on a label nobody emits matches nothing and pages forever through `noDataState` (#2035 review).
  - `reachable`: `1` when a TCP connect to the node's Tailscale IP on its probe port (a per-node field in `targets.txt`, 22 by default) succeeds within 5 s (`nc -z -w 5`, present in the pinned `restic/restic:0.19.1` image), and `0` otherwise.
- `targets.txt` gains each node's Tailscale IP and its ADR-028 class (`always-on` or `on-demand`). Both are generated from `networking.*` in `common.yaml` by `make sync-r2-watcher-targets` and are never hand-written.
- A new Grafana rule fires for an **on-demand** node that is reachable and whose newest snapshot is older than 3 × `node_backup_interval` (3 h). It computes the per-node product of `snapshot_age_seconds` and `reachable`, so it never filters on `reachable` and an off node never turns into "no data". The condition must hold across two consecutive probes. It stays silent while the node is off: that case is the `infra`/`vpn` ping monitor's, which is not muted.
- A second Grafana rule fires when a node's `raw_bytes` drops by more than 50 % between consecutive probes (operator decision, 2026-10-02). Per the probe's boundary ("a size is never a health check"), this judgement lives in the rule, never in `healthy`.
- **No node-side change.** `make provision` check mode on beelink and rpi4 changes no `node_backup` task. (Until 2026-10-03 this read "stays `changed=0`", which drift outside this spec makes unmeasurable on these nodes, #2039.)

## Out of scope

- Freshness on always-on nodes (vps, rpi3): their unmuted heartbeat already covers it.
- The comparative "snapshot older than the newest source write" rule from the issue's 2026-08-15 comment. It needs the node to report its source mtime, which reintroduces a node-side component.
- A Prometheus or Uptime Kuma metrics datasource, and unmuting the `on-demand` tag.
- The absolute 48 h rule in the issue title, which this spec supersedes.
- Shipping node journals to Loki.

## Risks / open questions

- **Rejected alternatives:**
  - A freshness check inside the ship script cannot see a ship that never ran.
  - A second node-side timer shares systemd and the role with the thing it guards; a dead systemd or a removed role silences both.
  - The watcher is the only always-on component that depends on none of the node's own units.
- **Boot window:** a node probed in its first minutes after boot is reachable and still carries its pre-shutdown snapshot. The first ship comes 2 min + up to 5 min after boot. The rule reads `last_over_time` over a window longer than the 6 h cadence, so each probe's value holds until the next one, and `for: 7h` then demands two consecutive stale probes. **Limit:** the LogQL harness (AC2) evaluates the expression, not Grafana's `for:` state machine, so `for >= 7h` is pinned by a static test and not exercised end to end.
- **Reachability from the pod:** pods reach tailnet IPs (the Uptime Kuma EndpointSlice to `100.64.0.6:3001`), and the Headscale policy accepts `kubelab@ → *:*`. Port 22 on beelink and rpi4 from the watcher pod is not yet measured; the first task measures it. A port refused by ufw or sshd would read `reachable=0` forever: a silent false negative that looks like "node off". Two defences:
  - The port is a per-node field in `targets.txt` (Glances, bound to the Tailscale IP, is the fallback), never hardcoded.
  - The always-on nodes are a positive control. The watcher runs on the VPS, so `reachable=0` for an always-on node means a broken probe, not a node that is off, and the health verdict reports it.
- **`unwrap` drops `null`:** a restic failure leaves `snapshot_age_seconds` `null`, LogQL marks the line `__error__`, and that series vanishes. If every on-demand node fails this way, the freshness rule goes to no data and pages alongside the health rule (readable=0). That is a double page, not a defect, and the annotation says so. For the shrink rule it is intended: a change from `null` to a number is not a drop.
- **Restic time format:** the snapshot `time` is RFC 3339 with nanoseconds and possibly a zone offset, and busybox `date` is weak on both. The parse is measured in the pinned image and tested with the `Z` and `+HH:MM` forms. A failed parse yields `null`, never `0`.
- **Shrink threshold, resolved 2026-10-02:** 50 %. `forget` plus `prune` legitimately shrinks raw data when retention drops old snapshots, but never by half in one 6 h window on this fleet.
- **Live proof, resolved 2026-10-02:** a fixture test on the rule expressions plus one real prod watcher run reporting the new fields. No prod node is stalled on purpose.
- **Filtering trap:** a rule that keeps only `reachable="1"` lines has no data whenever every on-demand node is off. With `noDataState: Alerting`, that pages every night. The product form in What avoids this, and AC2 tests it.
- **`noDataState`:** `Alerting` carries two causes (a stall, or a watcher that stopped reporting). Following the #1377 note in `disk-rules.yaml`, the annotation must name both, never assert one.

## Acceptance criteria

- [ ] **AC1** Every `r2_backup_node` line carries `newest_snapshot` (ISO 8601 UTC), `snapshot_age_seconds` (both `null` when restic fails) and `reachable` (`0` or `1`), plus the node's `class` (`always-on` or `on-demand`) copied from `targets.txt`, which the freshness rule filters on. `tests/test_r2_backup_watcher_probe.py` covers: a readable repository, a restic failure (`null`, never a fresh-looking value), a reachable host and an unreachable one.
- [ ] **AC2** The freshness rule fires for an on-demand node that is reachable on two consecutive probes with `newest_snapshot` older than 3 h. It does not fire for an unreachable on-demand node, nor for any always-on node, and it does not go to "no data" when every on-demand node is off. All of this is proven by a test that evaluates the rule expression against fixture lines.
- [ ] **AC3** The shrink rule fires when consecutive `raw_bytes` for one node drop by more than 50 %, and does not fire on a `null` size. Proven by a fixture test.
- [ ] **AC4** `targets.txt` takes each node's Tailscale IP and class from `common.yaml` through `make sync-r2-watcher-targets`. `make validate-sync` fails if they drift.
- [ ] **AC5** Live in prod, one watcher run, read from Loki: every node reports `newest_snapshot` and `snapshot_age_seconds`. vps and rpi3 report `reachable=1`, and so does at least one on-demand node that is up at that moment (the positive control). `make provision` check mode on beelink and rpi4 changes no `node_backup` task (reworded 2026-10-03 after the archive review: the earlier `changed=0` was unmeetable for drift outside this spec, tracked in #2039).
- [ ] **AC6** The health verdict treats `reachable=0` on an always-on node as unhealthy (a broken probe), and `tests/test_r2_backup_watcher_probe.py` covers it.

## References

- Bitácora: mlorentedev/kubelab#485, under epic #1923, sequenced in #1727 (OBS-027).
- ADR-028 (always-on and on-demand classes).
- BACKUP-044 AC9 (the coverage heartbeat and its muting), BACKUP-055 (the watcher probe), BACKUP-057 Q3 (`raw_bytes`), OBS-015 (`disk-rules.yaml`, the two-cause `noDataState`).
- OBS-018 (#1377): an alert that fired from its first day because its LogQL had never been evaluated; the reason AC2 runs the real expression.
- `infra/ansible/roles/node_backup/templates/node-backup-capture.service.j2` (the AC9 comment), `infra/k8s/base/services/r2-backup-watcher/probe.sh`, `infra/k8s/base/services/grafana-alerting/r2-backup-rules.yaml`.
