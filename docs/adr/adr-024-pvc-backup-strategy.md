---
id: adr-024-pvc-backup-strategy
type: adr
status: active
created: "2026-03-21"
owner: manu
---


# ADR-024: PVC Backup Strategy

## Status

Accepted (2026-03-22). **The Backblaze B2 leg is superseded by [ADR-049](adr-049-edge-object-storage-placement-doctrine.md)** (2026-06-19): the off-site `tier-offsite` is Hetzner Storage Box + Borg (bulk) + Cloudflare R2 (critical subset); B2 is retired.

## Context

KubeLab is approaching production cutover (ADR-023 Phase 2). Four PVCs contain critical stateful data:

- **gitea-data**: Git repositories + SQLite metadata DB
- **authelia-data**: User database, TOTP secrets, session data (SQLite)
- **n8n-data**: Workflow definitions + credentials (SQLite)
- **minio-data**: Object storage (S3-compatible)

Before real data accumulates, we need a minimum viable backup strategy. Three existing protection layers already exist but each has gaps:

| Layer | What it protects | Gap |
|-------|-----------------|-----|
| Hetzner VPS snapshots | Full disk | Crash-consistent only — SQLite can corrupt. No granular restore. |
| Ansible backup role | Docker Compose volumes | Obsolete post-cutover (K3s replaces Compose). File copy, not app-consistent. |
| (none) | K3s PVCs | No backup exists yet |

## Decision

### MVP (Phase 2): CronJob + tar + MinIO

Deploy a K8s CronJob in the **prod overlay only** (staging data is disposable):

- **Schedule**: Daily at 03:00 UTC (05:00 CEST)
- **Image**: `alpine:3.21` with `sqlite3` (apk) + `mc` (downloaded at runtime, arch-aware)
- **PVCs backed up**: gitea-data, n8n-data, authelia-data (read-only mounts)
- **Consistency**: `sqlite3 .backup` API for all SQLite databases before tar (application-consistent snapshots)
- **Destination**: MinIO bucket `kubelab-backups` (auto-created)
- **Retention**: 7 days rolling
- **Credentials**: Existing `minio-secrets` K8s Secret

### minio-data excluded

Backing up MinIO to MinIO is circular. minio-data backup deferred to Phase 5 (off-site — target revised by ADR-049 from B2 to Hetzner Storage Box / R2).

### Migration path (Phase 5): Velero + MinIO + B2

Replace this CronJob with Velero for:
- CSI volume snapshots (if supported)
- Off-site backup to Backblaze B2
- Integrated restore workflow
- All PVCs including minio-data

## Alternatives Considered

| Option | Verdict |
|--------|---------|
| Velero + MinIO | Correct long-term (Phase 5) but too much overhead for 4 PVCs now |
| Velero + B2 | Requires B2 account setup — deferred |
| CronJob + tar + B2 | Same CronJob but off-site — easy to switch endpoint later |
| Host-level script (kubectl cp) | Fragile, not K8s-native, no RBAC |
| Application-level dumps (gitea dump, etc.) | Most consistent but different per service, complex to orchestrate |

## Consequences

### Positive

- Application-consistent SQLite backups (sqlite3 .backup API)
- Granular restore per PVC (not all-or-nothing like VPS snapshots)
- Automated daily — no manual intervention
- Zero custom images — Alpine + runtime install
- Clear migration path to Velero

### Negative

- mc binary downloaded on every run (~25MB) — acceptable for daily job
- minio-data not backed up (circular) — mitigated by Hetzner snapshots until Phase 5
- Backup stored on same node as source — not off-site (mitigated by Hetzner snapshots)

### Risks

- RWO PVCs assume single-node K3s. Multi-node requires nodeAffinity on CronJob.
- SQLite DB file paths hardcoded — must update if services change DB locations.
- MinIO CDN outage prevents mc download — backup job fails (non-critical, retries next day).

## Defense in Depth (post-cutover)

| Layer | Protects against | Granularity | Automated |
|-------|-----------------|-------------|-----------|
| K8s CronJob (this ADR) | Accidental deletion, data corruption | Per PVC, per day | Yes (daily) |
| Hetzner VPS snapshots | Disk failure, catastrophic loss | Full VPS | Manual / scheduled |
| Ansible backup role | Headscale/Traefik config loss | Per filesystem path | Manual (make backup) |
