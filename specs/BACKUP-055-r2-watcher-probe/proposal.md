---
id: "BACKUP-055-r2-watcher-probe"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-09-25"
issue: "mlorentedev/kubelab#1572"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal]
template_version: "1.0"
---

# BACKUP-055: a real R2 probe in r2-backup-watcher

## Why

<!-- from issue #1572: BACKUP-055: the fleet-wide R2 health check has no trigger — it only runs when a human types it -->

`r2-backup-watcher` runs every 6h and emits `{"metric":"r2_backup_health","healthy":1}` from a hardcoded `echo`. It never contacts R2. So `obs015-r2-backup-health` fires only when the CronJob itself stops, and three failures stay silent:
- a revoked or rotated read credential;
- a node whose repository is gone or empty;
- a snapshot missing one of the sources `backup.sources` declares.

`make backup-coverage` is the only check that reads R2, and it runs only when someone types it. Its `1 path(s)` is the staging dir, so it proves a snapshot exists, not what the snapshot holds. The per-node controls (a Kuma push monitor per ship, `OnFailure=` to Slack, a weekly `restic check`) answer "did this node's backup run". None answers "can the destination still be read, and does every node's newest snapshot hold what we declared". This check is also the only one that works with the homelab powered off.

## What

The watcher reads R2 on its existing 6h schedule, from inside the cluster, with a **read-only** R2 token and the restic repository password. For every node in `backup.sources` it checks four things, and nothing else:

1. **Readable:** `restic snapshots` opens the node's repository. This catches a wrong password, a revoked token or a missing repository.
2. **Non-empty:** at least one snapshot exists.
3. **Complete:** every declared source is a directory in the newest snapshot, `/opt/node-backup/staging/<service>/`. The layout was measured on 2026-09-26 in all four repositories; the node → repository mapping follows `repository_name()` (`vps` → `kubelab-vps`).
4. **Whole capture:** the newest snapshot contains `/opt/node-backup/staging/.capture-complete`. `node-backup-capture.sh` writes this sentinel last, only if every source was staged, and `node-backup-ship.sh` refuses to ship without it. That guard lives on the node. This check verifies it from the destination: a snapshot without the sentinel means the guard regressed, or someone ran a `restic backup` by hand that bypassed it. It answers "was the capture whole", never "is it fresh". The same `ls` answers it, so it costs nothing extra.

Output keeps the Loki → Grafana contract, so the rule and its test stay as they are:
- one line per node, `{"metric":"r2_backup_node","node":…,"readable":…,"snapshots":…,"missing":[…],"healthy":0|1}`, for the operator;
- then **one fleet line**, `{"metric":"r2_backup_health","healthy":0|1}`, which is what `obs015-r2-backup-health` reads. It is 1 only if every node is healthy. A per-node `healthy` under the rule's current `last_over_time(...) by (namespace)` would let a healthy node emitted last mask a failing one.

**It does not judge age.** `coverage()` refuses to on purpose: age belongs to each node's Kuma push monitor, which knows the node's class. Two age controls could silently disagree (issue comment, 2026-09-25).

Also in this change: the rule's `runbook_url` points at `docs/runbooks/backup-restore.md`, which does not exist. It becomes `offsite-backup-restore.md`, with a section on this alert.

## Out of scope

- **Snapshot age, and #485's "backup older than the data".** Kuma owns age, and #485 stays open.
- **The write round-trip** (`health-check`'s put/get/delete) and the issue body's original AC1–AC4 (a schedule for `health-check`, a `make` target for it, a `page` envelope via n8n). The re-scope (2026-09-24/25) replaced them: a read-only token cannot write, and write failures already reach Slack through each node's `OnFailure=`. AC3 and AC4 survive in a different form: the mutation proof and "a healthy run does not fire the rule".
- **`restic check` from the cluster.** It needs a lock, meaning write access, and each node already runs it weekly.

## Risks / open questions

- **R1: the cluster gains read access to every backup.** The restic password decrypts all four repositories: Authelia's and n8n's databases, Gitea, Kuma. Decided by the operator on 2026-09-24. Mitigations: the R2 token is Object Read only and scoped to `kubelab-backups`, so the cluster can never `forget`/`prune`. The Secret is read only by this CronJob's pod. It lives in both clusters, because the watcher is in `base/` and observability changes are validated in staging first (ADR-028 amendment 2026-08-09).
- **R2: read-only restic.** `snapshots` and `ls` normally take a lock, which is a write. The probe runs `--no-lock --no-cache` (measured working on 2026-09-26 with the full-access token). **It must be re-measured with the read-only token before the manifest is written**; that is task 1.
- **R3: runtime.** A recursive `ls latest` took 92 s on the Beelink (the Gitea tree). The probe lists only the staging dir's direct children (`restic ls latest /opt/node-backup/staging`, non-recursive). `activeDeadlineSeconds` is sized from one timed in-cluster run, not guessed.
- **R4: a probe that dies emits nothing.** Every failure path, including restic erroring, a timeout or a missing env var, must still produce the per-node `healthy:0` line and the fleet `healthy:0` line. Silence would read as noData only after the rule's 24h window.

## Acceptance criteria

- [ ] AC1: in prod, a healthy fleet produces four `r2_backup_node` lines with `healthy:1` and one `r2_backup_health` line with `healthy:1` per run, visible via `toolkit obs logs`, and `obs015-r2-backup-health` is `Normal`.
- [ ] AC2: the probe cannot write. With the watcher's credential, `aws s3 cp` into the bucket is refused, while `restic snapshots` succeeds.
- [ ] AC3: mutation proof in staging. Each of the following turns the fleet line to `healthy:0` and fires the rule, then reverts. None of them edits the shared Secret or the bucket; each is a throwaway Job created with `kubectl create job --from=cronjob/r2-backup-watcher`, then patched.
  - a declared source that does not exist: a fake service in that Job's targets;
  - a node with no repository: a fake node in that Job's targets;
  - a wrong restic password: `RESTIC_PASSWORD` overridden on that Job only;
  - a missing sentinel: that Job's sentinel name overridden to one no snapshot contains.
  The unit tests cover the same four branches, and the crash and timeout paths, with a fake `restic`.
- [ ] AC4: the targets (node, repository, sources) are generated from `backup.sources` and never hand-written. A test fails if the committed file and the SSOT disagree.
- [ ] AC5: the image is `restic/restic` pinned through `IMAGE_SOURCES`, and a test asserts that its tag equals `backup.r2.restic_version`, so the watcher reads with the same restic that writes.
- [ ] AC6: the rule's `runbook_url` resolves to a file in the repo, and a test asserts it.

## References

- Issue #1572, with the re-scope and correction comments of 2026-09-24/25. Epic #1090, phase [5].
- `toolkit/features/backup_destination.py`: `coverage()`, `repository_name()`, `repo_url()`.
- BACKUP-044 (`specs/archive/BACKUP-044-*`): the node pipeline and the AC9 Kuma coverage monitors.
- ADR-049 D3 (R2), ADR-028 (monitoring of record; observability manifests in the shared base).
