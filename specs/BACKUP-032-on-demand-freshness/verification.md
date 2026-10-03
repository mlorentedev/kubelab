---
tags: [spec, verification, templates]
created: "2026-10-01"
---

# Verification - BACKUP-032-on-demand-freshness

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] **AC1** -> commit `c7d5b480` / `tests/test_r2_backup_watcher_probe.py` (the field, offset, several-snapshot, null-on-failure, unreadable-time and reachable/unreachable tests)
- [x] **AC2** -> commit `7d29f469` / `tests/test_r2_backup_freshness_rule.py`: `test_a_reachable_on_demand_node_that_stopped_shipping_fires`, `test_the_freshness_rule_stays_silent[*]` (off, turned off, fresh, always-on), `test_every_on_demand_node_off_is_a_zero_never_no_data`, evaluated in the pinned Loki against lines printed by the real probe
- [x] **AC3** -> commit `7d29f469` / `test_the_shrink_rule_fires_only_on_a_drop_of_more_than_half[*]` (including the `null` size), `test_a_single_probe_never_reads_as_a_shrink`
- [x] **AC4** -> commit `5c81b815` / `tests/test_r2_watcher_targets.py` (IP, port and class from networking; a missing field raises); `make validate-sync` compares the committed `targets.txt`
- [x] **AC5** -> measured 2026-10-02 after #2037 and #2038 merged (also on #485), against the AC as reworded on 2026-10-03 (see "Review dispositions"):
  - `make watcher-run NAME=r2-backup-watcher ENV=prod` succeeded in 379 s. Read from Loki (`toolkit obs logs --env prod`), one line per node, each with `newest_snapshot` set:
    - `vps` (always-on): `reachable=1`, `healthy=1`, `snapshot_age_seconds` 7894
    - `rpi3` (always-on): `reachable=1`, `healthy=1`, `snapshot_age_seconds` 610
    - `beelink` (on-demand, up: positive control): `reachable=1`, `healthy=1`, `snapshot_age_seconds` 1274
    - `rpi4` (on-demand, up: positive control): `reachable=1`, `healthy=1`, `snapshot_age_seconds` 1745
  - Against prod Loki after #2038: the freshness expression answers one value per on-demand node, the shrink expression one per backup node (1.0005 to 1.19). `make alerts`: nothing firing.
  - `make provision NODE=bee ENV=prod CHECK=1`: `changed=3`, all known check-mode noise (apt cache and upgrade, #1594; Docker GPG key, #1426).
  - `make provision NODE=rpi4 ENV=prod CHECK=1`: `changed=15`: 4 check-mode noise (#1594, #1426 and the handler it queues), 3 known coredns drift, 8 role changes never applied to the node (sshd, `/etc/hosts`, node_maintenance), tracked in #2039.
  - `node_backup` tasks changed: 0 on beelink, 0 on rpi4. This spec changed no Ansible.
- [x] **AC6** -> commit `c7d5b480` / the always-on down and always-on hang tests in `tests/test_r2_backup_watcher_probe.py`

## Test status

- Test suite: `make test` -> 3598 passed, 1 failed (`platform.json` stale after the `common.yaml` edit), fixed in `6c989e45`; `tests/test_sync_platform_json.py` 26 passed after it. `make lint` passes.
- Manual smoke test (staging, 2026-10-02): Argo CD `kubelab-staging` repointed to the branch (`master` → branch), then `make watcher-run NAME=r2-backup-watcher ENV=staging`, Job succeeded in 209 s. Every node line carried the new fields: beelink (on-demand) age 3463 s, rpi4 (on-demand) 133 s, rpi3 (always-on) 9758 s, vps (always-on) 2403 s, all `reachable=1`, `healthy=1`; the fleet line read `nodes=4 unhealthy=0`. Staging runs on ace1, LAN-adjacent to the homelab, so this proves the probe and its parsing in the pinned image, not reachability from the VPS (that is AC5).
- No regressions in existing test suite: yes

## Measurements (2026-10-02)

- **Time format.** Read through the toolkit (`backup_destination.coverage` with a recording `run`), shape only: beelink, rpi3 and rpi4 answer `YYYY-MM-DDTHH:MM:SS.<8 or 9 digits>+HH:MM`, and vps answers `...<9 digits>Z`. The fraction length varies (Go trims trailing zeros), and the offset is the source node's.
- **Pinned image (`restic/restic:0.19.1`, BusyBox v1.37.0).** `date -u -d "YYYY-MM-DD HH:MM:SS" +%s` and `date -u -d @<epoch>` work, `sed -E` works, and `nc -z -w 2` answers rc 0 for an open port, rc 1 for a refused one and rc 1 after the timeout for a blackholed address. `date -d` does not take an ISO string with an offset, and `$((08))` is an arithmetic error in BusyBox and dash, so the probe splits the offset with `sed -E` and strips its leading zero.
- **Reachability: the pod probe was replaced, by decision.** The task asked for `nc` from a pod in prod. No codified path runs an ad-hoc pod, and a hand-typed `kubectl run` in prod is what the repo rules forbid. It is replaced by three pieces of evidence:
  1. The IaC: port 22/tcp is in `base_system`'s fleet-wide `firewall_allowed_ports` and in `networking.firewall.vps_inbound`, and `sshd_config.j2` listens on `0.0.0.0`.
  2. A staging watcher run before merge. Staging runs on ace1, which is LAN-adjacent to beelink and rpi4, so that run proves the probe works, not prod reachability.
  3. AC5 after merge, the real measurement from the VPS pod, with vps and rpi3 as the positive control.

## Decisions made during implementation

- `class` is emitted on every `r2_backup_node` line and AC1 now names it (#2035 review, recorded on #485): the freshness rule filters on it, and a filter on a label nobody emits pages forever through `noDataState`.
- **The rule multiplies by `reachable`, it never filters on it.** A filter on `reachable="1"` answers "no data" whenever the homelab is off, and `noDataState: Alerting` would page on the normal state. The product answers 0 for each off node (lesson-509).
- **An unreadable snapshot time fails the node, closed.** `newest_epoch_of` fails if any `time` stamp does not parse, and the node is unhealthy with reason `snapshot time unreadable`, so a restic output change pages through the health rule instead of reading as age 0.
- **`NC` is an override, for the tests.** Ubuntu's busybox `sh` runs its own `nc` applet (which has no `-z`) ahead of `PATH`, so the tests pass the fake by path. The pinned image uses the default `nc`.
- **The Loki harness evaluates the rule as written,** read from the rules YAML, in the image prod pins. Slots lie in the future because a throwaway Loki answers "no data" for ranges older than 3 h (lesson-510). It needs only a local docker and no cluster access; CI fails, never skips, without docker.

## Correction after merge (2026-10-02)

The rules as merged in #2037 (`a19f5a2e`) grouped `by (node)`. In prod, Vector sets a `node` stream label (the K8s node), so `| json` renamed the probe's field and every backup node fell into one series. Read against prod Loki minutes after merge, the shrink rule gave 0.477 (vps last over beelink first) and would have paged on every evaluation. AC2 and AC3 evidence from `7d29f469` is therefore void. It is replaced by the fix PR: the rules extract `backup_node`, the harness takes its stream labels from Vector's sink with one `pod` per run, and two cross-node tests fail on the merged rules (6 failed, 12 passed against `a19f5a2e`'s rules). After the fix, prod Loki gives the corrected shrink expression one value per backup node: 1.19, 1.0005, 1.02 and 1.04. lesson-512.

## Review dispositions (2026-10-03)

First archive review (`nan/deepseek-v4-flash`, FAIL on `6ad0c6c7`):

1. **Major, `f5` was a vacuous checkbox grep.** Applied: `f5` now reads the AC5 block and fails unless each of the four nodes has a `reachable=1` line with a numeric age, and both provision runs report 0 `node_backup` changes.
2. **Minor, AC5 ticked while `changed=0` was unmet.** Applied: AC5 and the "No node-side change" line in `proposal.md` are reworded to the checkable intent (no `node_backup` task changes). The original wording is quoted in both places; the drift that made it unmeetable is #2039.
3. **Major, `tasks.md` edited after the review captured its digests.** Applied by re-running the review on the final contract set, not by reverting the ticks.
4. **Minor (theoretical), alert windows retyped in the tests.** Applied: the freshness test reads the probe interval from the CronJob `schedule:` and the on-demand ship interval from `node_backup_interval`, and asserts the rule's `for:` and the shrink window each outlast one probe interval and the threshold is at least three ship intervals (`test_the_alert_windows_follow_the_cadences_they_depend_on`).

## Promotion candidates

Answer each line `yes: <path>`, naming the file you promoted, or `no: <reason>`. `dotf spec archive` refuses a line left unanswered, a `no` without a reason, and a `yes` whose file does not exist; a `00_meta/` path is looked up in the vault.

- [x] Lesson for the repo's `docs/lessons/`? yes: `docs/lessons/observability/lesson-509-a-check-inside-the-unit-cannot-see-the-unit-not-running.md`, `docs/lessons/observability/lesson-510-loki-answers-no-data-for-ranges-older-than-3h-it-never-flushed.md` and `docs/lessons/observability/lesson-512-a-json-field-named-like-a-stream-label-is-renamed-and-the-grouping-moves.md`
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no: the alerts follow the existing watcher design (BACKUP-055) and ADR-028's always-on/on-demand split; nothing new was decided at architecture level
- [x] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. no: lessons 510 and 512 are specific to this Loki/Vector stack, and lesson-509's principle has one occurrence so far, below the >1-project bar

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/BACKUP-032-on-demand-freshness/` -> `specs/archive/BACKUP-032-on-demand-freshness/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
