---
tags: [spec, tasks, templates]
created: "2026-09-25"
---

# Tasks - BACKUP-055-r2-watcher-probe

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers** (optional, additive — borrowed from `github/spec-kit`, adapt-not-adopt per #141):
> - `[P]` — this task has **no dependency on another unchecked task**, so it is safe to run in parallel (fan out to a `Workflow`, or just batch). TDD chains (test → implement → refactor of the *same* behavior) are sequential and must NOT carry `[P]`; independent behaviors can.
> - `[AC<n>]` — this task helps satisfy **acceptance criterion #`<n>`** from `proposal.md`. Lets `/spec check` map coverage deterministically; omit it and the check falls back to semantic judgment.

## Setup

- [x] Branch `feat/backup-055-r2-watcher-probe` from master (✓ 2026-09-26)
- [ ] The operator approves `proposal.md`
- [x] (✓ 2026-09-26) **Manual (operator):** create the Cloudflare R2 token, Object Read only, scoped to `kubelab-backups`. Store both halves with `toolkit secrets set backup.r2.readonly_{access_key_id,secret_access_key} --env common --stdin`. Steps in `docs/runbooks/offsite-backup-restore.md` (task 9).

## Implementation

1. [x] (✓ 2026-09-26) [AC2] **Measure first (R2).** With the read-only token: `restic --no-lock --no-cache snapshots` and `ls latest /opt/node-backup/staging` succeed on all four repositories, and an `aws s3 cp` into the bucket is refused. Record the output in `verification.md`. If `--no-lock` is not enough, stop and revise the proposal.
2. [ ] [P] [AC4] Test first, `tests/test_r2_watcher_targets.py`: the committed `infra/k8s/base/services/r2-backup-watcher/targets.txt` equals the render from `backup.sources` plus `repository_name()`, one `<node> <repository> <service>...` line per node. Watch it fail.
3. [ ] [AC4] Add the renderer (`toolkit/features/backup_destination.py`, `watcher_targets()`) and `toolkit sync r2-watcher-targets`, generate the file, and serve it through `configMapGenerator` `files:`. The hash is kept: each Job pod reads it fresh, but a hash is never wrong. Green.
4. [ ] [P] [AC5] Test first: `backup.watcher_image` is in `IMAGE_SOURCES`, its tag equals `backup.r2.restic_version`, and `kustomization.yaml` `images:` carries it. Then add the SSOT key and run `make sync-k8s-images`. Green.
5. [ ] [P] [AC1] Catalog `backup.r2.readonly_access_key_id` and `backup.r2.readonly_secret_access_key`: `SecretKind.EXTERNAL`, `envs=("staging","prod")`, stored in common. Add a `SecretMapping` `r2-backup-watcher-secrets` holding `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` and `RESTIC_PASSWORD`. Test the mapping, following `test_k8s_secrets_vikunja_r2.py`.
6. [ ] [AC1] [AC3] Test first, `tests/test_r2_backup_watcher_probe.py`: run the probe script under `sh`, with a fake `restic` on PATH, to prove:
   - healthy → 4 node lines plus fleet `healthy:1`;
   - missing source, no repository, bad password, restic crash or missing env → the failing node's line plus fleet `healthy:0`, never silence (R4).
   Watch it fail.
7. [ ] [AC1] [AC3] Write the probe (`infra/k8s/base/services/r2-backup-watcher/probe.sh`, served by the same generator). Rewrite the CronJob: image, Secret env, targets mount, `RESTIC_CACHE_DIR` on an emptyDir, and `activeDeadlineSeconds` set after task 10's timing. Green. `tests/test_r2_backup_alerting_rules.py` stays green unchanged.
8. [ ] [P] [AC6] Test that the rule's `runbook_url` names an existing file, then fix it to `offsite-backup-restore.md`.
9. [ ] [AC6] Runbook section: what the alert means, how to read the per-node lines, and how to rotate the read-only token, including the click-by-click creation.
10. [ ] [AC1] [AC3] Staging: point `targetRevision` at the branch **after reading it and coordinating with the other lanes**, then `make apply-secrets ENV=staging`. Trigger one Job (`kubectl create job --from=cronjob/...`), time it and read the lines. Run the three mutations from AC3: each turns the fleet line to 0 and fires the rule in staging Grafana. Revert, and set `targetRevision` back to master.
11. [ ] [AC1] Prod after merge: `make apply-secrets ENV=prod`, one Job, four healthy lines, rule `Normal`.

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` (see below) with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PR opened referencing this spec folder

## Machine-readable features

This spec emits a sibling `features.json` (alongside this file) following [[pattern-feature-list-as-primitive]]. The JSON is the harness-facing contract: each acceptance criterion maps to ≥1 feature with `id`, `behavior`, `verification` (executable command), `state` (lifecycle), and `evidence` (harness-captured output).

**Pass-state gating:** the agent CANNOT write `"state": "passing"` — only the harness, after running `verification` and capturing exit code 0, may set that terminal state. Reviewers must reject PRs where features.json contains `passing` entries with empty `evidence`.

Minimal `features.json` skeleton (drop into `<repo>/specs/BACKUP-055-r2-watcher-probe/features.json`):

```json
[
  {
    "id": "BACKUP-055-r2-watcher-probe-f1",
    "behavior": "<one-line copy of an acceptance criterion>",
    "verification": "<single shell command; exit 0 means pass>",
    "state": "pending",
    "evidence": ""
  }
]
```
