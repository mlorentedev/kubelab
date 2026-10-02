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

- `r2-backup-watcher` adds two fields to each `r2_backup_node` line:
  - `newest_snapshot`: the time of the newest snapshot, ISO 8601 UTC, read with the same `restic snapshots --latest 1` call, for the operator to read.
  - `snapshot_age_seconds`: the age of that snapshot at probe time. It is a measurement, not a verdict, so the probe still judges no age. It exists because LogQL can `unwrap` a number but not a timestamp.
  - Both are `null` when restic cannot answer, never a value that reads as fresh.
  - `reachable`: `1` when a TCP connect to the node's Tailscale IP on port 22 succeeds within 5 s (`nc -z -w 5`, present in the pinned `restic/restic:0.19.1` image), and `0` otherwise.
- `targets.txt` gains each node's Tailscale IP and its ADR-028 class (`always-on` or `on-demand`). Both are generated from `networking.*` in `common.yaml` by `make sync-r2-watcher-targets` and are never hand-written.
- A new Grafana rule fires for an **on-demand** node that is reachable and whose newest snapshot is older than 3 × `node_backup_interval` (3 h). It computes the per-node product of `snapshot_age_seconds` and `reachable`, so it never filters on `reachable` and an off node never turns into "no data". The condition must hold across two consecutive probes. It stays silent while the node is off: that case is the `infra`/`vpn` ping monitor's, which is not muted.
- A second Grafana rule fires when a node's `raw_bytes` drops by more than 50 % between consecutive probes (operator decision, 2026-10-02). Per the probe's boundary ("a size is never a health check"), this judgement lives in the rule, never in `healthy`.
- **No node-side change.** `make provision` on beelink and rpi4 stays `changed=0`.

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
- **Boot window:** a node probed in its first minutes after boot is reachable and still carries its pre-shutdown snapshot. The first ship comes 2 min + up to 5 min after boot. Requiring the condition on two consecutive probes (6 h cadence) absorbs this. **Resolve before tasks:** confirm how `for:` composes with `last_over_time` over a 6 h series, using the existing `r2-backup-rules.yaml` and `disk-rules.yaml` as the reference.
- **Reachability from the pod:** pods reach tailnet IPs (the Uptime Kuma EndpointSlice to `100.64.0.6:3001`), and the Headscale policy accepts `kubelab@ → *:*`. Port 22 on beelink and rpi4 from the watcher pod is still unmeasured; measure it in the first task.
- **Shrink threshold, resolved 2026-10-02:** 50 %. `forget` plus `prune` legitimately shrinks raw data when retention drops old snapshots, but never by half in one 6 h window on this fleet.
- **Live proof, resolved 2026-10-02:** a fixture test on the rule expressions plus one real prod watcher run reporting the new fields. No prod node is stalled on purpose.
- **Filtering trap:** a rule that keeps only `reachable="1"` lines has no data whenever every on-demand node is off. With `noDataState: Alerting`, that pages every night. The product form in What avoids this, and AC2 tests it.
- **`noDataState`:** `Alerting` carries two causes (a stall, or a watcher that stopped reporting). Following the #1377 note in `disk-rules.yaml`, the annotation must name both, never assert one.

## Acceptance criteria

- [ ] **AC1** Every `r2_backup_node` line carries `newest_snapshot` (ISO 8601 UTC), `snapshot_age_seconds` (both `null` when restic fails) and `reachable` (`0` or `1`). `tests/test_r2_backup_watcher_probe.py` covers: a readable repository, a restic failure (`null`, never a fresh-looking value), a reachable host and an unreachable one.
- [ ] **AC2** The freshness rule fires for an on-demand node that is reachable on two consecutive probes with `newest_snapshot` older than 3 h. It does not fire for an unreachable on-demand node, nor for any always-on node, and it does not go to "no data" when every on-demand node is off. All of this is proven by a test that evaluates the rule expression against fixture lines.
- [ ] **AC3** The shrink rule fires when consecutive `raw_bytes` for one node drop by more than 50 %, and does not fire on a `null` size. Proven by a fixture test.
- [ ] **AC4** `targets.txt` takes each node's Tailscale IP and class from `common.yaml` through `make sync-r2-watcher-targets`. `make validate-sync` fails if they drift.
- [ ] **AC5** Live in prod: one watcher run reports `reachable` and `newest_snapshot` for all four nodes, read from Loki. `make provision` on beelink and rpi4 reports `changed=0`.

## References

- Bitácora: mlorentedev/kubelab#485, under epic #1923, sequenced in #1727 (OBS-027).
- ADR-028 (always-on and on-demand classes).
- BACKUP-044 AC9 (the coverage heartbeat and its muting), BACKUP-055 (the watcher probe), BACKUP-057 Q3 (`raw_bytes`), OBS-015 (`disk-rules.yaml`, the two-cause `noDataState`).
- `infra/ansible/roles/node_backup/templates/node-backup-capture.service.j2` (the AC9 comment), `infra/k8s/base/services/r2-backup-watcher/probe.sh`, `infra/k8s/base/services/grafana-alerting/r2-backup-rules.yaml`.
