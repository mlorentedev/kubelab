---
tags: [spec, verification, templates]
created: "2026-09-25"
---

# Verification - BACKUP-055-r2-watcher-probe

## Evidence

Implementation merged in #1851 (`871ffce2`); the staging and prod evidence in #1857 (`313538fc`). Each criterion's executable check is in `features.json`, all six exit 0 on 2026-09-27.

- [x] AC1 -> `871ffce2` / `tests/test_r2_backup_watcher_probe.py`, `tests/test_r2_backup_watcher_manifest.py`, `tests/test_k8s_secrets_r2_watcher.py`; live in prod (Task 11)
- [x] AC2 -> `test_the_probe_never_takes_a_lock`, `test_the_write_credential_never_reaches_the_cluster`; the refusals measured by hand (Task 1)
- [x] AC3 -> `test_each_breakage_fails_its_node_and_the_fleet` and the missing-Secret, missing-targets and empty-fleet cases; four staging mutations fired the rule (Task 10)
- [x] AC4 -> `bc5996dd` / `tests/test_r2_watcher_targets.py`
- [x] AC5 -> `05034bb5` / `test_the_watcher_reads_with_the_restic_that_writes`
- [x] AC6 -> `tests/test_alert_runbook_urls.py`
- Pre-review by a Claude reviewer subagent (2026-09-27, at `313538fc`; not the archive gate, which only a pool model may sign): all six MET, 73 passed, no blocking defect. Its three minor findings: this block, `features.json` and the Closing list were unfilled (fixed here); the shell count below was misstated (fixed here); the fake-source Loki line lost to GC (already recorded in Task 10, now lesson-470).

### Task 1: the read-only token, measured 2026-09-26

The token is `kubelab-r2-watcher`, an account token with "Workers R2 Storage Bucket Item Read" on `kubelab-backups` only, no expiry and no IP filter. It is stored at `backup.r2.readonly_{access_key_id,secret_access_key}` in `common.enc.yaml`. The measurement ran from the workstation and printed only rc and restic output:

- `restic --no-lock --no-cache snapshots --json --latest 1`: rc=0 on all four repositories, n=1, 1.2 to 1.6 s each.
- `restic --no-lock --no-cache ls latest /opt/node-backup/staging`, non-recursive: rc=0, 2.2 to 2.9 s each. Direct children:
  - beelink `gitea`;
  - rpi3 `uptime_kuma`;
  - rpi4 `pihole`;
  - vps `authelia`, `headscale`, `n8n`.
  Every node also has `.capture-complete`. The recursive listing took 92 s on the Beelink (R3).
- Negative controls:
  - restic **without** `--no-lock` → rc=1 `unable to create lock in backend: client.PutObject: Access Denied`;
  - `aws s3 cp` into the bucket → rc=1 `AccessDenied` on PutObject.
  - A delete control was deliberately not run: the only real object to aim it at is a repository file, and a mistaken grant would have destroyed that repository.
- Conclusion: R2 is resolved. `--no-lock` is both required and sufficient, and AC2's refusal half is observed.

### AC4: generated targets (2026-09-26, `bc5996dd`)

- `make sync-r2-watcher-targets` writes `infra/k8s/base/services/r2-backup-watcher/targets.txt` on the first run and reports `unchanged` on the second. The render (`beelink beelink gitea`, `rpi3 rpi3 uptime_kuma`, `rpi4 rpi4 pihole`, `vps kubelab-vps authelia headscale n8n`) matches the repositories and directories measured in R2 in task 1.
- `tests/test_r2_watcher_targets.py`: 4 passed. Mutation: appending a line to the committed file turns `test_the_committed_targets_match_the_ssot` red with `... is stale. Regenerate it with make sync-r2-watcher-targets`. Restored from HEAD, it is green again. `toolkit sync r2-watcher-targets --check` reports `is current`.

### AC5: image pin (2026-09-26, `05034bb5`)

- `backup.watcher.image: restic/restic:0.19.1` in `IMAGE_SOURCES`, and `make sync-k8s-images` synced 11 tags. `restic/restic:0.19.1` exists on Docker Hub for amd64 and arm64.
- Mutation: bumping only the image to 0.19.2 turns `test_the_watcher_reads_with_the_restic_that_writes` red. Restoring it turns it green.

### AC1 (delivery): the watcher's Secret (2026-09-26, `3294d9b9`)

- `r2-backup-watcher-secrets` carries `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` (both read-only) and `RESTIC_PASSWORD`, with no optional keys. A missing value refuses the apply.
- Mutation: pointing `AWS_ACCESS_KEY_ID` at the nodes' read-write `BACKUP_R2_ACCESS_KEY_ID` turns `test_the_write_credential_never_reaches_the_cluster` red.
- `make secrets-audit`: staging 58/58. Prod 80/84: the 4 missing are the `resume` Actions secrets, missing on master too, none of them this change's.

### AC1/AC3: the probe (2026-09-26, `db9ff02e`)

- `tests/test_r2_backup_watcher_probe.py`: 16 cases × {dash `sh`, busybox 1.37.0 `sh`} = 32 passed. The image's own shell was checked by a separate manual run in the container, not by this parametrisation. Mutations:
  - a fleet verdict that ignores unhealthy nodes → 16 failed;
  - the `EXIT` trap removed → 8 failed (the missing-Secret and missing-targets paths go silent).
- **Real run** in `restic/restic:0.19.1`, `--read-only` rootfs with `/tmp` tmpfs, the read-only token, and the committed targets: 4 × `r2_backup_node` `healthy:1` with `sentinel:1` and `missing:[]`, then `r2_backup_health` `nodes:4 unhealthy:0 healthy:1`. rc=0, 16.4 s including container start.
- **Real red run**, same image, with mutated targets (`rpi3` plus a fake source `canary`, and a node `ghost` with no repository):
  - `rpi3` → `missing:["canary"] healthy:0 reason:"missing sources"`;
  - `ghost` → `readable:0 ... repository does not exist`;
  - fleet `nodes:2 unhealthy:2 healthy:0`; rc=1; 4.9 s.

### AC1/AC3: the CronJob (2026-09-26, `e55be964`, `f2fbb112` before the rebase)

- `tests/test_r2_backup_watcher_manifest.py` renders both overlays and asserts: the image equals `backup.watcher.image`; `envFrom` names the one `SecretMapping` for the watcher; the mounted `probe.sh` and `targets.txt` are byte-equal to the committed files, at the directory of the probe's own `WATCHER_TARGETS` default; the command is `sh probe.sh` with no `-e`; `backoffLimit: 0`, `restartPolicy: Never`, `Forbid`; no service account token; `/tmp` on an emptyDir under a read-only root. It also checks that the probe's `STAGING_DIR`/`SENTINEL` defaults equal the `node_backup` role's.
- **The deadline cannot silence the probe.** Kubelet signals PID 1 only, and `sh` runs its trap once the running `timeout restic` returns. So `activeDeadlineSeconds` (600) is asserted greater than nodes × 2 × `RESTIC_TIMEOUT` (480), and `terminationGracePeriodSeconds` (90) greater than one `RESTIC_TIMEOUT` (60). Both values are read from the probe and the targets, not copied. Mutations: grace 30 s → red; deadline 180 s (the old value) → red.
- restic as uid 65534 on a read-only rootfs with a tmpfs `/tmp`: `snapshots --no-lock --no-cache` and `ls latest` work (a throwaway local repository, 2026-09-27).

### AC6: runbook links (2026-09-26)

- `tests/test_alert_runbook_urls.py`: every `runbook_url` in `grafana-alerting/` names a committed file and, when it carries an anchor, a heading with that GitHub slug. Red on two rules at first: `obs015-r2-backup-health` **and** `obs015-pvc-unbound-failure` both pointed at `docs/runbooks/backup-restore.md`, which does not exist. Mutation: renaming the runbook heading → red.
- The runbook section is `offsite-backup-restore.md#r2-backup-alert`.

### Task 10: staging (2026-09-27)

Coordinated with both kubelab lanes (`kubelab-7d`, `kubelab-vikunja-migration-wt-55`); both replied OK before the repoint. `targetRevision` was `master` before, `feat/backup-055-r2-watcher-probe` during.

- `make apply-secrets ENV=staging DRY_RUN=1`: only `r2-backup-watcher-secrets` `created`, every other Secret `unchanged`. Applied by the operator; the second run was all `unchanged` (also seen as a `deploy-k8s` prerequisite: 12 × `unchanged`).
- Argo CD synced the branch: the live CronJob carries `restic/restic:0.19.1` and `activeDeadlineSeconds: 600`.
- **Healthy run**: 4 × `r2_backup_node` `healthy:1`, fleet `nodes:4 unhealthy:0 healthy:1`. 21 s from Job start to completion, pod start included. Peak memory (cgroup `memory.peak`, a throwaway Job): **46 MiB**.
- **AC3 mutations**, four throwaway Jobs from the CronJob, the Secret and the bucket untouched:
  - fake source (`rpi3 … ghost_service`) → `missing:["ghost_service"]`, fleet `nodes:4 unhealthy:1 healthy:0`;
  - fake node `ghost` → `readable:0`, `repository does not exist`, fleet `nodes:5 unhealthy:1 healthy:0`;
  - `RESTIC_PASSWORD` overridden on the Job → 4 × `wrong password or no key found`, fleet `unhealthy:4 healthy:0`;
  - `SENTINEL=.no-such-sentinel` → 4 × `no capture sentinel`, fleet `unhealthy:4 healthy:0`.
- The lines reached staging Loki, except the fake-source Job's: the CronJob controller adopts Jobs created `--from` it, and with 4 failed at once `failedJobsHistoryLimit: 3` deleted the oldest Job and its pod within about a minute, before Vector read the file. An artifact of four concurrent failures; a real failed run is kept.
- **Rule**: `obs015-r2-backup-health` FIRING in staging at 00:50Z (the last bad line at 00:29:34Z; `interval: 10m` plus `for: 10m`), with the new summary and runbook link. After the mutation Jobs were deleted and one healthy Job ran (00:58Z, fleet `healthy:1`), the rule was no longer firing at 01:07:51Z.

- **`deploy-k8s` twice: done for the parts that can show it.** The operator ran it with staging back on master (871ffce2); two runs got past the confirmation prompt. On both, `apply-secrets` was 12 × `unchanged` and `sync all --check` in sync. The Kustomize apply is server-side and prints `serverside-applied` for every object whether or not it changed, so its output cannot show a no-op; Argo CD reporting `Synced` at the same revision is the evidence that live already matched. The chained `import-n8n` is not idempotent: each run re-imports master's workflows and restarts n8n (twice, then 4 times), which overwrote a parallel lane's staging import (lane notified both times).

### Task 11: prod (2026-09-27, after #1851 merged as `871ffce2`)

- Argo CD synced the merge: the live CronJob carries `restic/restic:0.19.1` and `activeDeadlineSeconds: 600`.
- `make apply-secrets ENV=prod` (operator): `r2-backup-watcher-secrets` `created`, the other 11 `unchanged`, nothing restarted.
- One Job (`r2bw-t11-prod`), 01:37:50Z → 01:38:25Z: 4 × `r2_backup_node` `healthy:1` with `sentinel:1` and `missing:[]`, fleet `nodes:4 unhealthy:0 healthy:1`. All five lines in prod Loki (`toolkit obs logs --env prod`), and `make alerts ENV=prod` shows nothing firing.
- Review coverage of #1851: PR-Agent only. CodeRabbit was rate-limited on every head and Codex had no quota.

### Pool review dispositions (2026-09-27)

`review.md`: `nan/deepseek-v4-flash`, PASS-WITH-GAPS at `31ab9314`, no Blocker.

- Major, a last target with no trailing newline is never probed: **applied** in #1866, with a regression test that was red under dash and busybox.
- Minor, "is a directory" versus path presence: **deferred** to #1865 (BACKUP-056). Theoretical; no R2 repository holds such a file.
- Minor, `test_the_probe_never_takes_a_lock` survives a direct `restic` call: **applied** in #1866. The fake restic refuses a locking call and the test reads the calls; the reviewer's mutation now goes red.
- Minor, `toolkit sync all` skips `r2-watcher-targets`: **applied** in #1866, so `validate-sync` and CI now check it.
- Minor, R4's wording: **clarified here**. On a global failure (missing env var, unreadable or empty targets file) there is no node to name yet, so the owed artifact is the single fleet line with `healthy:0`, which `test_a_pod_without_its_secret_still_reports_unhealthy` and `test_missing_targets_still_report_unhealthy` assert. A per-node `healthy:0` line is owed only once a node has been read from the targets.

## Test status

- Test suite: `make test` → 2823 passed, 15 skipped, 1 xfailed (the OPS-023 AC5 guard), rc=0, on the rebased #1851 head.
- Manual smoke test: tasks 10 and 11 above.
- No regressions in existing test suite: yes.

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- The watcher reports; it does not judge age. Freshness stays with each node's own `OnFailure=` path, and the fleet line is healthy only when every node's latest snapshot is readable, holds its sentinel and every declared source.
- One fleet line plus one line per node, so the Grafana rule did not change and the per-node lines carry the diagnosis.
- `activeDeadlineSeconds` and `terminationGracePeriodSeconds` are derived from `RESTIC_TIMEOUT` and the targets count, and a test holds both inequalities, because a deadline kill that lands before the trap prints leaves the Job silent for 24 h.
- PR-Agent's "missing manual trigger" was deferred to #1858 (TOOL-084); `deploy-k8s` re-importing n8n on every run, found during task 10, is #1859 (TOOL-085).

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes - lesson-465 (a read-only restic token needs `--no-lock`), lesson-466 (a backup copy before a template reports changed), lesson-470 (a Job made from a CronJob is pruned by its history limit).
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? no - the watcher's shape is a spec-level decision, recorded above.
- [x] New pattern candidate for `00_meta/patterns/`? no - nothing here has recurred in another project.

## Archive checklist

- [x] (✓ 2026-09-27) `proposal.md` frontmatter set to `status: archived`
- [x] (✓ 2026-09-27) Folder moved: `specs/BACKUP-055-r2-watcher-probe/` -> `specs/archive/BACKUP-055-r2-watcher-probe/`
- [x] (✓ 2026-09-27, `Closes #1572` in the archive PR) Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [x] (✓ 2026-09-27; lessons 465, 466, 470 are in `docs/lessons/`; the review names 469, the number before a collision with master) Promotions above executed (if any)
