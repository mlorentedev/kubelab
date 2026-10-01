---
id: "BACKUP-046-postgres-dump"
type: spec
status: archived # draft | implementing | verifying | archived
created: "2026-10-01"
issue: "mlorentedev/kubelab#1111"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, backup]
template_version: "1.0"
---

# BACKUP-046: Postgres is backed up, and no claim can go unruled again

## Why

<!-- from issue #1111: BACKUP-046: the PVC consumer class — three of five ratified claims have no backup at all -->

Prod's Postgres (`kubelab/postgres-data`) holds every Vikunja user, project and task, and it has no backup. `common.yaml` excluded it on 2026-08-22 because it was "measured empty … it joins this list the day something writes to it". Vikunja started writing on 2026-08-27. #1111 recorded that on 2026-09-03, with evidence, and nothing changed until the operator asked on 2026-10-01 whether a restart could lose the board. The data survived only because nothing broke.

The defect is the shape of the exclusion, not the missing line. A deferral with a trigger nobody watches is a promise, and the existing guard (`tests/test_backup_volume_coverage.py`) covers only Docker volumes on the Beelink. PVCs have no guard at all.

An emergency `pg_dumpall` was taken from the workstation on 2026-10-01 06:51Z and restored into a scratch `postgres:16-alpine`. Users, projects, tasks and labels match live row for row. That copy is a stopgap kept outside the repository; this spec replaces it.

## What

Inventory, measured 2026-10-01 (`kubectl kustomize infra/k8s/overlays/prod` and `kubectl get pvc -A` on prod):

| Claim | Ruling today | Ruling after this spec |
|---|---|---|
| `kubelab/authelia-data` | backed up (`pvc` + `sqlite`) | unchanged |
| `kubelab/n8n-data` | backed up (`pvc` + `sqlite`) | unchanged |
| `kubelab/postgres-data` | prose exclusion, lapsed | **backed up (`pvc` + `pg_dumpall`)** |
| `kubelab/grafana-data` | prose exclusion | excluded, tier 3 (operator, 2026-09-29) |
| `kubelab/loki-data` | prose exclusion | excluded, tier 3 (operator, 2026-09-29) |
| `kubelab/crowdsec-db` | prose exclusion | source (`sqlite: crowdsec.db`), ratified tier 2 in #452, kept by the operator 2026-10-01 (Q1) |
| `kubelab/crowdsec-config` | none | excluded, see Q1 |
| `kube-system/traefik` (ACME) | none, and absent from the manifests | excluded, tier 3 (operator, 2026-09-29: "ACME … rebuilt") |

1. **Capture by logical dump.** `backup.sources.vps.postgres` declares `pvc: {namespace: kubelab, claim: postgres-data}` and a new capture method, `pg_dumpall: {deployment: postgres, container: postgres}`, a sibling of `sqlite`.
   - The capture script runs `pg_dumpall -U "$POSTGRES_USER"` inside the running container through `kubectl exec`, with the k3s kubeconfig it already uses to resolve PVC paths. The user comes from the container's own environment, so the dump cannot drift from the user the database was initialised with.
   - It writes to `$STAGING/postgres/pg_dumpall.sql` through a temporary file, then refuses the capture unless the file ends with pg_dumpall's `-- PostgreSQL database cluster dump complete` trailer. A truncated dump fails loudly and the sentinel is never written, so ship refuses it.
   - With `pg_dumpall`, the claim's data directory is **not** copied. A file copy of a running Postgres is inconsistent, the same reason SQLite sources use `.backup`.
2. **Exclusions are a ratified tier, never a deferral.** `backup.excluded.vps` gains one entry per excluded claim, each with `pvc: {namespace, claim}`, a `reason`, and `tier: 3`. A test refuses any exclusion whose tier is not 3: data that is not rebuildable is backed up, and "not yet" is not a ruling. The Beelink volume exclusions gain `tier: 3` under the same rule.
3. **Static guard.** A test renders `infra/k8s/overlays/prod` and fails if any `PersistentVolumeClaim` has no ruling: neither in `backup.sources.vps` nor in `backup.excluded.vps`. It fails on today's master, which lists five claims without one.
4. **Live guard.** `make backup-coverage ENV=prod` also lists every PVC on the prod cluster, in all namespaces, and reports any claim with no ruling. This catches what the manifests do not render, such as `kube-system/traefik`, which Ansible creates.
5. **Restore drill.** `make backup-drill-postgres ENV=prod` restores the newest `postgres/pg_dumpall.sql` from the VPS repository in R2 into a throwaway `postgres:16-alpine` on the workstation, loads it, and checks that it restored completely: every database and table live holds exists in the restore, and no table that has rows live came back empty. Per-table counts are printed beside live as information, never as a pass condition, because the snapshot is up to four hours older than live and the board keeps being written. It prints counts, never row contents, and removes the container and the restored file on every exit path. It uses the image the live Deployment runs, so the restore exercises the same major version. Scheduling it is #1211 (BACKUP-051), not this spec.

## Out of scope

- A schedule for the drill. #1211 owns the cadence and the "drill overdue" signal (epic #1923, decision 4).
- Vikunja attachments in the `kubelab-vikunja` R2 bucket. They are a single copy, and Q2 asks where that belongs.
- Point-in-time recovery (WAL archiving, `pg_basebackup`). The epic sets Vikunja at RPO 24h, and the VPS ships every 4h.
- The per-node buckets and lock of BACKUP-057 (#1920). This spec writes into whatever repository ship targets.

## Risks / open questions

- **Q1 (operator, answered 2026-10-01: keep tier 2): keep `crowdsec-db` at tier 2, or downgrade it?** #452 (restated in #1111's 2026-08-16 inventory) ratified `crowdsec-db` as tier 2 and `crowdsec-config` as tier 3; the epic's 2026-09-29 table does not list either. The first draft of this spec proposed tier 3 for both and encoded that as an exclusion, which made an unanswered question read as a ruling (PR-Agent on #1979). This spec now applies the ratified ruling: `crowdsec-db` is a source, `crowdsec-config` stays excluded. Downgrading `crowdsec-db` is the operator's call; it would lose this instance's own alert history, while CAPI re-sends the community blocklist.
- **Q2: Vikunja attachments.** Filed as #1981, a child of #1923 next to BACKUP-057, covering the attachment bucket with the same lock or a second copy.
- **Risk: `kubectl exec` against a Deployment** picks one pod. With `strategy: Recreate` and one replica there is one, and during a rollout the exec fails, which fails the capture loudly and pages through `node_notify`. The next 4h run retries. Measured from the workstation on 2026-10-01: the exec reaches the container and `pg_dumpall` authenticates over the local socket with no password.
- **Risk: a dump is larger than its data.** 74 KB today. The R2 size alert from BACKUP-057 PR 1 bounds the repository.

## Acceptance criteria

- [x] AC1: On prod, `make backup-node NODE=vps ENV=prod` ships a snapshot that contains `postgres/pg_dumpall.sql`, ending with the completion trailer, and no file from the claim's data directory.
- [x] AC2: A capture whose `pg_dumpall` fails, or whose output lacks the trailer, exits non-zero and leaves no sentinel. Pinned by a test that runs the rendered script against a fake `kubectl`.
- [x] AC3: The static guard fails on master's `common.yaml` and passes after this spec, and any exclusion without `reason` or with a tier other than 3 fails it.
- [x] AC4: `make backup-coverage ENV=prod` names every live PVC with no ruling, and reports none after this spec.
- [x] AC5: `make backup-drill-postgres ENV=prod` restores the newest dump from R2 into a scratch database and passes: the trailer is present, every live database and table exists in the restore, and no table with rows live is empty in it. It also names the snapshot it read, which is AC1's evidence. The transcript is in `verification.md`.
- [x] AC6: `docs/runbooks/offsite-backup-restore.md` documents the Postgres restore, and the procedure for adding a stateful service to the fleet. A lesson records why the exclusion lapsed.

## References

- Epic: #1923 (BACKUP-060). Tier table and the build-on-the-platform rule: its decisions 1 and "Build on the platform's own tools".
- Existing guard this generalises: `tests/test_backup_volume_coverage.py`.
- Capture script: `infra/ansible/roles/node_backup/templates/node-backup-capture.sh.j2`.
- Runbook: `docs/runbooks/offsite-backup-restore.md`.
