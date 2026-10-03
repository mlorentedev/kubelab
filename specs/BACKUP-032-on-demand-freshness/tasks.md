---
tags: [spec, tasks, templates]
created: "2026-10-01"
---

# Tasks - BACKUP-032-on-demand-freshness

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Spec PR merged (`docs/backup-032-spec`, Refs #485) ✓ 2026-10-02 (#2035)
- [x] Implementation branch from master: `feat/backup-032-on-demand-freshness` ✓ 2026-10-02; new worktree gets `poetry.lock` copied before `make worktree-init` (DEBT-015 #1128)
- [x] Before touching `targets.txt`: re-read BACKUP-057 (#1959) for changes to the watcher or `backup_destination.py` (none on 2026-10-02) ✓ 2026-10-02

## Implementation

Measurements first, then the probe, then the harness, then the rules.

- [x] [P] [AC5] **Measure reachability** ✓ 2026-10-02 (replaced, see `verification.md`) from a pod in the prod `kubelab` namespace, using the pinned `restic/restic:0.19.1` image: `nc -z -w 5 <tailscale_ip> 22` for vps, rpi3, and beelink/rpi4 while they are up. Record rc per node in `verification.md`. If 22 is refused on a homelab node, take that node's Glances port as its probe port.
- [x] [P] [AC1] **Measure the time format:** ✓ 2026-10-02 one `restic snapshots --json --latest 1` per repository, through the toolkit. Record only the *shape* of `time` (fraction digits, `Z` or offset), never ids or paths beyond what `make backup-coverage` already prints. Then find the busybox `date` invocation that parses it in the pinned image.
- [x] [AC4] Failing test: `toolkit sync r2-watcher-targets` renders `<node> <repo> <id> <tailscale_ip> <port> <class> <sources>...` from `networking.*` and `backup.sources`; `--check` fails on a hand edit.
- [x] [AC4] Extend `_sync_r2_watcher_targets` (`toolkit/features/backup_destination.py`) and regenerate `targets.txt`. Update `probe.sh`'s reader in the same commit, so the format and its reader never drift apart.
- [x] [AC1] Failing tests in `tests/test_r2_backup_watcher_probe.py`, using the fake-restic harness: `newest_snapshot` and `snapshot_age_seconds` for a readable repository; both `null` on a restic failure and on an unparseable time; ages for the `Z` and `+HH:MM` forms; `reachable` 1 and 0 with a fake `nc`.
- [x] [AC1] Implement in `probe.sh`, measurement only: no age threshold in the probe.
- [x] [AC6] Failing test: an always-on node with `reachable=0` makes the node and the fleet line unhealthy, with reason `probe cannot reach an always-on node`. An on-demand node with `reachable=0` stays healthy.
- [x] [AC6] Implement in `probe.sh`.
- [x] [AC2] **LogQL harness** (`tests/loki_harness.py`): start the pinned `grafana/loki:3.6.4` with a minimal single-binary config, push fixture lines with controlled timestamps to `/loki/api/v1/push`, and run a rule's `expr` **read from the rules YAML, never retyped** as an instant query at a chosen time. Skip when docker is absent locally and fail in CI, following `tests/test_oauth_tokens_not_logged.py`. Declare `allow_host_clients(reason=...)` per TEST-003. Prove it by running the existing `obs015-r2-backup-health` expression against a healthy fixture and an unhealthy one.
- [x] [AC2] Failing harness tests for the freshness rule. These cases must FIRE: on-demand, reachable, age > 3 h. These cases must stay SILENT: on-demand unreachable, always-on stale, on-demand fresh, every on-demand node off (a series is still present: no "no data").
- [x] [AC2] Add the freshness rule to `r2-backup-rules.yaml`. Its expression is `last_over_time(age)` times `last_over_time(reachable)` by node, filtered on `class="on-demand"`, then `> 10800`. It also sets `for: 7h` and `noDataState: Alerting`, and its annotation names both causes and the double page with the health rule. Add a static test that pins `for >= 7h` and the class filter.
- [x] [AC3] Failing harness tests for the shrink rule. A drop of more than 50 % between two probes FIRES. A 30 % drop, a 2× growth, a single probe and a `null` size stay SILENT.
- [x] [AC3] Add the shrink rule: `last_over_time / first_over_time < 0.5` over a window of about 9 h, by node. Fill in `runbook_url` and the section it points to in `docs/runbooks/offsite-backup-restore.md`.
- [x] Refactor `probe.sh` and the harness for clarity. `make lint` and `make test` must pass. ✓ 2026-10-03: no separate pass; #2038 reshaped the harness (stream labels read from Vector's sink), and lint and test passed at both merges and on the archive branch
- [x] [AC5] ✓ 2026-10-02 (see `verification.md`) After merge, run the prod watcher once (`make watcher-run NAME=r2-backup-watcher ENV=prod`) and read it from Loki (`toolkit obs logs`). Record per node `reachable` and whether `snapshot_age_seconds` is a number, never the raw values. Run `make provision NODE=bee ENV=prod` and the same for rpi4 (or their check mode) and confirm `changed=0`.

## Closing

- [x] Every acceptance criterion from `proposal.md` is covered by at least one test ✓ 2026-10-03 (AC1-AC4 and AC6 by tests; AC5 is a live prod measurement by definition, recorded in `verification.md`)
- [x] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command ✓ 2026-10-03 (f1-f6 passing)
- [x] `make lint` and `make test` pass ✓ 2026-10-03 (3614 passed, archive branch on `0a06c085`)
- [x] No unrelated changes in the diff ✓ 2026-10-03
- [x] lesson-509 written ✓ 2026-10-02 (506 to 508 held by other lanes), plus lesson-510 (the Loki harness) (a check inside the unit it guards cannot see the unit not running; filtering on a field turns "all off" into "no data")
- [ ] `verification.md` filled in; independent `dotf spec review` (different model) before archive
- [x] Runbook: the new alerts' section in `docs/runbooks/offsite-backup-restore.md`

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/BACKUP-032-on-demand-freshness/features.json`):

```json
[
  {
    "id": "BACKUP-032-on-demand-freshness-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
