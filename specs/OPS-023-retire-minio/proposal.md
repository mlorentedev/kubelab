---
id: "OPS-023-retire-minio"
type: spec
status: implementing # draft | implementing | verifying | archived
created: "2026-09-22"
issue: "mlorentedev/kubelab#972"   # repo#NNN — GitHub issue / Project item that tracks this spec
tags: [spec, proposal, minio, backup, retirement]
template_version: "1.0"
---

# OPS-023: retire MinIO everywhere

## Why

<!-- from issue #972: OPS-023: MinIO is deployed twice, in K8s and on beelink -->

MinIO was adopted in March 2026 (ADR-023, ADR-028) as the platform's single object store, with three planned uses:
- backups through Velero, replicated to Backblaze B2;
- Loki chunks;
- CI artifacts.

None of them was built. ADR-049 retired B2 and moved the off-site tier to R2 and Hetzner Storage Box. Loki uses `object_store: filesystem`. CI runs on GitHub-hosted runners.

Its one real use was the prod `pvc-backup` CronJob (`infra/k8s/overlays/prod/backup.yaml`). That CronJob has **failed every night since 2026-08-25 with no alert** (#972, #1171). Meanwhile the same PVCs have been backed up to R2 by `node_backup` (BACKUP-044), and that path was restore-exercised on 2026-08-22.

ADR-061 D4 deferred MinIO's fate until "the real offsite path exists". It does now. The operator decided on 2026-09-23 to retire MinIO everywhere rather than carry three idle deployments, and the reason is to avoid accumulating debt.

MinIO also runs **three times**: K8s prod, K8s staging, and Docker Compose on the Beelink. Upstream, the community edition is in maintenance mode, and it has had no admin UI or console SSO since `RELEASE.2025-05-24`.

## What

After this change:

- **No MinIO runs anywhere.** The K8s Deployment, Service, IngressRoutes and `minio-data` PVC are gone from staging and prod, and the Beelink container and its data directory are gone. The Beelink teardown lives in the role that still owns the node, `beelink_services`, because Ansible is additive: removing a template does not remove what it installed.
- **The `pvc-backup` CronJob is gone.** The PVCs it covered are backed up to R2 by `node_backup`.
- **The `minio` OIDC client is gone**, together with:
  - its entry in `apps.services.security.authelia.oidc_clients`;
  - the `MINIO_IDENTITY_OPENID_*` consumer env;
  - its SOPS keys, retired through the frozen-orphan path (#1513).
  This absorbs #1784.
- **Every secondary reference is removed or rewritten:**
  - SSOT values and `SECRET_CATALOG`;
  - homepage tiles, the platform manifest and e2e expectations;
  - DNS records, if any;
  - Uptime Kuma monitors, if any;
  - CLAUDE.md, and docs that describe current state.
- **ADR notes:**
  - ADR-061 D4 records the decision it deferred;
  - ADR-024's CronJob is marked retired;
  - ADR-028's Beelink line drops MinIO.
- **Object storage keeps a contract, not a server.** Per ADR-049 D1/D2, apps that need objects talk the S3 API to a configured endpoint, which is R2 today (Vikunja already does this). A self-hosted S3 comes back only when a specific app needs one. It would then be a maintained implementation, not MinIO community, and its volume would go in `backup.sources` so `node_backup` ships it to R2.

**Naming trap, stated once:** `kubelab-backups` names both the **MinIO** bucket being deleted and the **R2** bucket that stays. Every line in this spec says which one it means.

## Out of scope

- **Any change to the R2 backup path** (`node_backup`, `backup.sources`, the R2 `kubelab-backups` bucket).
- **A replacement object store.** None is needed today (see What).
- **BACKUP-049 (#1171).** Its subject, the CronJob, disappears here. Closing it or re-scoping it to a dead man's switch for the R2 ship is decided on that ticket.
- **The restore-drill cadence** (#1211).

## Risks / open questions

- **R1: data destruction. Resolved 2026-09-23.** The operator confirmed deleting `minio-data` in both environments:
  - prod holds 14 `pvc-backup` tarballs (5.0 MiB, newest 2026-08-25), superseded by R2 snapshots with about a year of retention;
  - staging is empty;
  - the Beelink holds 88 KB and no data.
  Evidence before and after is `kubectl get pvc` and the bucket listing, recorded in `verification.md`.
- **R2: order against SSOT-017 (#1780). Resolved 2026-09-23.** #1780 owns `oidc_clients` and the Authelia config files. The implementation of this spec starts from master **after #1780 merges**. Only this spec is written before that.
- **R3: Argo CD pruning.** Removing the manifests from git lets Argo CD prune the Deployment and the PVC in prod, which has `selfHeal: true`, and in staging on sync. The PVC's reclaim policy decides whether the local-path volume is deleted with it. **Measured 2026-09-23:** both `minio-data` PVs are `local-path` with `persistentVolumeReclaimPolicy: Delete`. Pruning the PVC therefore deletes the data on disk as well; nothing is left orphaned on the node. This is what R1 authorises. Check whether the Argo CD Application prunes PVCs at all (`syncOptions`, `prune`), so that the deletion happens by GitOps and not by hand.
- **R4: residual consumers.** The inventory says nothing outside the repo writes to any instance, but a consumer inside the repo can be missed: a Makefile target, a toolkit command, a test fixture, a homepage tile. The removal is driven by a full-repo sweep, and a guard asserts that no live file references MinIO outside the declared historical records.

## Acceptance criteria

- [ ] AC1: no MinIO workload, Service, IngressRoute, PVC or CronJob exists in staging or prod. The evidence is `kubectl get` output before and after, per environment.
- [ ] AC2: no MinIO container or data directory exists on the Beelink. A second `make provision NODE=bee ENV=prod` reports `changed=0`.
- [ ] AC3: `minio` is absent from `oidc_clients`, and the generated `oidc-clients.yml` for both environments no longer registers it. An authorization request for `client_id=minio` returns `invalid_client` in both environments.
- [ ] AC4: every MinIO SOPS key is retired through the frozen-orphan path, and `make secrets-audit` passes in every environment.
- [ ] AC5: a test fails if any live file (not an ADR, lesson, archived spec or changelog) references MinIO. It is shown red before the sweep and green after.
- [ ] AC6: `make backup-coverage` still reports every node covered after the removal. Nothing that backed up to R2 depended on MinIO.

## References

- Work gate: #972 (OPS-023). Absorbs #1784. Affects #1171 (BACKUP-049). Parent stream: #1775 (IDP-040).
- ADR-061 D4 (the deferral this spec resolves), ADR-049 D1–D3 (object-storage roles, R2), ADR-024 (the CronJob), ADR-023 and ADR-028 (MinIO's original placement).
- BACKUP-044 (`specs/archive/BACKUP-044-critical-subset-pipeline/`): the R2 path and its restore evidence.
- Upstream: minio/minio#21324 (console SSO removed in `RELEASE.2025-05-24`).
