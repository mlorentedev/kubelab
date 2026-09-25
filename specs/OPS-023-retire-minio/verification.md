---
tags: [spec, verification, templates]
created: "2026-09-22"
---

# Verification - OPS-023-retire-minio

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [ ] AC1 (K8s half, in the repo): `f798464b`. `kubectl kustomize` 2026-09-24: staging 96 objects, prod 99, with **0** MinIO and **0** `pvc-backup` references in either. Live before/after is pending staging validation and the prod prune.
  - Staging, partial (2026-09-25). Before, at 02:30:54Z: `deployment/minio`, `service/minio`, `pvc/minio-data`, `ingressroute/minio-api`, `ingressroute/minio-console` and `configmap/minio-config`; no `minio-secrets` Secret exists in staging. With `targetRevision` on this branch, Argo CD pruned the Deployment and the PVC within about 60 s. The run was cut short: staging belonged to #1825's lane, so the revision was restored and the other branch recreated MinIO (see #1825 and #1083). The full before/after run waits until staging is free.
  - **Staging, full run (2026-09-25).** At 02:40:01Z, before: `deployment/minio`, `service/minio`, `pvc/minio-data`, `ingressroute/minio-api`, `ingressroute/minio-console` and `configmap/minio-config`. `targetRevision` was set to this branch with the other lane's agreement. At 02:42:10Z, after: `Synced`/`Healthy` at `f01abfc0`, zero MinIO or `pvc-backup` objects, and no PV bound to `minio-data` (reclaim `Delete`, as R3 predicted). `make apply-secrets ENV=staging` reported `retired secret kubelab/minio-secrets absent`, and a second run changed nothing.
  - AC3, staging: `GET /api/oidc/authorization?client_id=minio` → `error=invalid_client`. Control `client_id=grafana` → `error=invalid_request` (known client, bogus redirect).
- [ ] AC2: PR 2.
- [ ] AC3 (repo half): `minio` is absent from both generated `oidc-clients.yml` (`make sync-oidc-hashes ENV=staging|prod`). The `invalid_client` probe is pending deployment.
- [ ] AC4 (OIDC half): `oidc_client_secret` and `oidc_client_secret_minio_hash` unset in dev, staging and prod. `make secrets-audit` exits 0 with no new orphan. `root_password` and `root_user` are PR 3.
- [ ] AC5: red on 2026-09-24. `pytest --runxfail tests/test_no_live_minio_references.py` fails with **93** live files, and lands as `xfail(strict=True)` (`6a6dbefb`).
- [ ] AC6: pending, after the prod prune.

## Test status

- Test suite: `make test` on 2026-09-24 -> `2645 passed, 15 skipped, 155 deselected, 1 xfailed` (the xfail is the AC5 guard).
- Manual smoke test: what was exercised, what was observed
- No regressions in existing test suite: yes / no (if no, document)

## Inventory (2026-09-23, read-only)

The data held in each instance: prod `kubelab-backups` (the **MinIO** bucket) has 14 objects and 5.0 MiB, newest 2026-08-25; staging has 0 objects; the Beelink holds 88 KB. Both PVs are `local-path` with reclaim policy `Delete`. `pvc-backup` last succeeded on 2026-08-25 and every run since has failed silently.

Repo: 135 files, by category:
- K8s: 8 files;
- Ansible: 9, with **no teardown task** in `beelink_services`;
- SSOT: 7;
- toolkit: 12;
- tests: 18;
- Terraform DNS: 1 (`services.json` `minio`, `console.minio`);
- Uptime Kuma: 3 monitors;
- docs: about 40, split into current-state and historical;
- Makefile: `backup-pvc` plus dev lists;
- Renovate: 1 pin;
- a **third** deployment definition, `infra/stacks/services/data/minio/` (the local dev Compose stack).

`.github/`: none. Spec collisions: BACKUP-049 (the CronJob) and VPNACL-001 (`tag:hermes → MinIO`).

## Decisions made during implementation

Brief log of non-obvious trade-offs or course corrections taken during the work. Routine choices belong in commit messages, not here.

- **PR order changed (2026-09-24).** The plan removed `apps.services.data.minio` and `root_password` in PR 1, but `provision-bee.yml` and the dev Compose stack read both, so `make provision NODE=bee` would have broken between merges. PR 1 now removes only what K8s reads. The SSOT block, `root_password` and the Renovate and `generator_traefik` bits move to PR 3.
- **The public `domain`/`console_domain` left `common.yaml` in PR 1.** `test_declared_domains_are_served` requires a DNS record for every declared public domain, and the records are gone. Nothing outside K8s read those keys; dev has its own `.test` values.
- **`docs/runbooks/pvc-backup-restore.md` was deleted in PR 1, not PR 3.** `test_runbook_targets_exist` fails on a runbook that names a removed `make` target.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [ ] Lesson for the repo's `docs/lessons/`? <yes / no - one line of what>
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/OPS-023-retire-minio/` -> `specs/archive/OPS-023-retire-minio/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
