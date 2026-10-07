---
tags: [spec, tasks, templates]
created: "2026-10-06"
---

# Tasks - BACKUP-075

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch created from master: `feat/backup-075-r2-bucket-size` (worktree `kubelab-backup-075-wt`) ✓ 2026-10-07
- [x] `proposal.md` is complete and acceptance criteria are testable ✓ 2026-10-07
- [x] No open questions left in `proposal.md` "Risks / open questions" (client and field name decided by the operator) ✓ 2026-10-07

## Implementation

### Measure first (no code)

- [x] [AC3] Baseline from Loki, not an ad-hoc client: the prod watcher's `stats took` lines for the last 7 days, and each node's last `raw_bytes`. Recorded in `verification.md`. ✓ 2026-10-07
- [ ] [AC3] The rclone side is measured by the first staging watcher run (task under *Roll out*), the way BACKUP-057 measured its sizes: staging reads the same four repositories. That run is also the gate for root listing: R2 tokens are scoped to buckets, not prefixes, so the read-only token's Object Read on `kubelab-backups` should list the root. If the run reports the bucket `null` with an access error, stop and take the scope question back to the operator.

### Image pin

- [ ] [P] [AC1] Failing test: the rclone image is pinned in `common.yaml` (`backup.watcher.size_image`, exact tag) and the kustomization `images:` entry matches it, the way `tests/test_r2_backup_watcher_manifest.py` already pins restic. Expected: FAIL.
- [ ] [AC1] Add the pin in `common.yaml`, the `images:` entry in `infra/k8s/base/kustomization.yaml`, and whatever `sync_k8s_images.py` needs. Expected: PASS.

### Init container and sizes file

- [ ] [AC1] [AC2] Failing manifest tests: an init container named `r2-size` runs `r2-backup-watcher/size.sh` in the rclone image, with the same Secret, non-root, read-only root filesystem, no capabilities, writing to an emptyDir that the probe container mounts read-only. `activeDeadlineSeconds` and the call count are recomputed from both scripts. Expected: FAIL.
- [ ] [AC1] [AC2] Failing tests for `size.sh`, run under `sh` against a fake `rclone` on PATH (same idiom as `test_r2_backup_watcher_probe.py`): it sizes each distinct bucket root once and each node prefix once, writes one line per bucket and per node, and writes `null` for any call that fails or prints no `bytes`. Expected: FAIL.
- [ ] [AC1] [AC2] Write `size.sh` and add it to the probe ConfigMap; configure rclone by environment only (`RCLONE_CONFIG_R2_TYPE=s3`, `PROVIDER=Cloudflare`, `ENV_AUTH=true`, `ENDPOINT` from `backup.r2.endpoint`). Bucket and prefix come from each target's repository URL, so `targets.txt` keeps its format. Expected: PASS.

### Probe reads the sizes

- [ ] [AC1] [AC2] [AC4] Failing probe tests: each node line carries `stored_bytes` from the sizes file; the fleet line's `stored_bytes` is the sum of bucket roots, each bucket once, and includes an object outside any prefix; a missing or `null` entry makes that node and the fleet `null`, and never changes `healthy`. Expected: FAIL.
- [ ] [AC1] [AC2] [AC4] `probe.sh`: drop `restic_stats` and `STATS_TIMEOUT`, read the sizes file, emit `stored_bytes`; keep the per-node timing line, now reporting the listing's duration from the sizes file. Shrink `terminationGracePeriodSeconds` to the new longest call. Expected: PASS.

### Rename the readers

- [ ] [AC5] Failing tests: `test_r2_backup_alerting_rules.py` and `test_r2_backup_freshness_rule.py` expect `unwrap stored_bytes` in the size and shrink rules, and a new assertion fails if `raw_bytes` appears in the watcher, its rules or the runbook. Expected: FAIL.
- [ ] [AC5] `grafana-alerting/r2-backup-rules.yaml` (both rules, their comments and summaries) and `docs/runbooks/offsite-backup-restore.md#cost-and-quota` read `stored_bytes` and say what it measures. Expected: PASS.

### Roll out

- [ ] [AC1] `make deploy-k8s ENV=staging`, then `make watcher-run NAME=r2-backup-watcher ENV=staging` at once: four numeric node sizes and a numeric fleet sum. Record in `verification.md`.
- [ ] [AC1] After merge and Argo CD sync, `make watcher-run NAME=r2-backup-watcher ENV=prod` at once (the rename empties the rule windows until a run lands), then confirm the free-tier alert resolves. Record in `verification.md`.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] `make test-fast` passes
- [ ] `make lint` passes
- [ ] No unrelated changes in the diff
- [ ] `verification.md` filled in
- [ ] Lesson if the measurement shows something non-obvious (next free number: 524)
- [ ] PR opened as a draft referencing this spec folder, `## Knowledge` section, `Closes #2077`

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/BACKUP-075/features.json`):

```json
[
  {
    "id": "BACKUP-075-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
