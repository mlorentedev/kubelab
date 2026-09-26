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
  - **Prod (2026-09-25/26, after #1788 merged at 04:08:20Z as `6abdea1b`).**
    - Before: not captured live. Argo CD synced the merge ten seconds later, before any session read the cluster. What stands in for it is the pre-merge render, `kubectl kustomize infra/k8s/overlays/prod` at `6abdea1b^`: 7 objects, `ConfigMap/minio-config`, `Service/minio`, `PersistentVolumeClaim/minio-data`, `Deployment/minio`, `CronJob/pvc-backup`, `IngressRoute/minio-api`, `IngressRoute/minio-console`.
    - Argo CD's own record (`kubelab-prod` `.status.operationState`): `Succeeded`, 04:08:30Z to 04:08:31Z, revision `6abdea1b`; `syncResult.resources` lists **3** as `Pruned`: `PersistentVolumeClaim/minio-data`, `Deployment/minio`, `CronJob/pvc-backup`. The other 4 are not in the operation's result, and it does not say how they left. The record does not settle it, so this line does not guess.
    - After, 2026-09-26: `kubectl get deploy,sts,pvc,cronjob,svc,cm,ingressroute,endpointslice -n kubelab` and `kubectl get pv` → no MinIO or `pvc-backup` object. Both Applications `Synced`/`Healthy` at `6abdea1b`, both on `targetRevision: master`.
    - `minio-secrets`: `make apply-secrets ENV=prod DRY_RUN=1` (#1834, run by the auth lane) read it **present**. Then `make apply-secrets ENV=prod` from master `6abdea1b` at 00:34:06Z, rc=0: `grafana-admin` configured (the auth lane's change), 10 Secrets unchanged, `retired secret kubelab/minio-secrets absent`, one restart (`deployment/grafana`). A second run: all 11 unchanged, `absent`, no restart. Independent read afterwards: `kubectl get secret minio-secrets -n kubelab` → `NotFound`. The real-run log says `absent` whether it deleted or found nothing, which is why the dry run's `present` is the only proof this run did the delete. Raised on #1834.
    - AC3, prod: `GET https://auth.kubelab.live/api/oidc/authorization?client_id=minio` → `error=invalid_client`. Control `client_id=grafana` → `error=invalid_request`.
    - Uptime Kuma: `make monitoring-apply` from master after the merge (it was not run before the merge, as the task asked): `Sync plan: 0 create, 0 edit, 3 delete (live=37, seed=34)`, removing `Services · Data · MinIO Prod` (479), `Services · Data · MinIO Console Prod` (480) and `Staging · Web · MinIO Staging` (489), confirmed gone. The first attempt timed out on the socket.io login and changed nothing. Re-run: `0 create, 0 edit, 0 delete (live=34, seed=34)`. `make alerts ENV=prod` was clean before it.
    - DNS: `make tf-dns-plan` from `~/Projects/kubelab`, the local-state checkout (#1499): `0 to add, 0 to change, 2 to destroy`, exactly `cloudflare_record.kubelab_svc["minio"]` and `["console.minio"]`, both `A 162.55.57.175`. Applied with the operator's OK: `2 destroyed`. Re-plan: `No changes`. `dig @denver.ns.cloudflare.com minio.kubelab.live` → `NXDOMAIN` (1.1.1.1 still served its cached answer for the rest of the 300 s TTL).
- [x] AC2: PR 2, `58d72b65`, run from the branch before merge.
  - Beelink before (2026-09-26, read-only): container `minio` (`quay.io/minio/minio:RELEASE.2025-09-07T16-13-09Z`) `Up 51 minutes (healthy)`; that image, 175 MB; `/opt/minio` 108K, holding only `data/`; ufw `9000/tcp` and `9001/tcp` `ALLOW` on `tailscale0`, v4 and v6. Docker 29.7.2.
  - `make provision NODE=bee ENV=prod CHECK=1`: rc=0, `changed=7`, `failed=0`. The container and image removals show `skipping` there because `command:` does not run in check mode.
  - Run 1: rc=0, `ok=136 changed=11 failed=0`. The four teardown tasks changed, then the compose template and systemd unit, and `Restart beelink services` recreated the stack once (Gitea and both runners, as announced to the operator). `Update apt cache`, `Upgrade all packages` and `Pull service images` also changed; they were already pending and have nothing to do with this change.
  - **Run 2: rc=0, `ok=132 changed=0 failed=0`.**
  - Beelink after (read-only): containers `act-runner`, `github-runner`, `gitea` (healthy), `glances` and the buildx builder, with no `minio`; no MinIO image; `/opt/minio` does not exist; no ufw rule for 9000 or 9001, v4 or v6; unit `Description=KubeLab Compose stack (Gitea, GitHub runners)`; `GET http://<beelink>:3000/api/healthz` → 200.
  - Headscale grant `tag:hermes → beelink:9000` (2026-09-26, from the branch, with the operator's OK):
    - `make deploy TARGET=vps ENV=prod CHECK=1` with `ANSIBLE_DIFF_ALWAYS=1` showed three changes. Only the hermes line is this PR. The other two were already on master and never deployed: `aws1` in the policy's hosts (destroyed 2026-08-23) and `ollama.kubelab.live → 100.64.0.5` in `config.yaml`'s `extra_records` (AI-007). The operator chose to converge them here, knowing the config change restarts Headscale.
    - Run 1: rc=0, `changed=5`. Config and policy templated, Headscale restarted and healthy, SIGHUP reload, and `Probe preserved mesh flows from the controller` ok.
    - Run 2: `changed=1`, all of it `Back up current ACL policy (for auto-revert)`, which copies the live policy over `.prev` on every run and so reports once after any policy change. Fixed in this PR (`changed_when: false`, the template task is what reports a policy change). Run 3, with the fix: rc=0, **`changed=0`**.
    - Live afterwards: `headscale` `healthy` (started 01:22:06Z); `headscale policy get` → `{ "action": "accept", "src": ["tag:hermes"], "dst": ["vps:443"] }`; no `ollama` in `config.yaml`. `tailscale ping` from the workstation answered from beelink, rpi3 and rpi4.
  - Uptime Kuma: the Beelink monitor's description dropped MinIO. `make monitoring-apply` from the branch: `0 create, 1 edit, 0 delete`; re-run `0/0/0`.
- [x] AC3: `minio` is absent from both generated `oidc-clients.yml` (`make sync-oidc-hashes ENV=staging|prod`), and `client_id=minio` → `invalid_client` in staging and prod (AC1 lines above).
- [ ] AC4 (OIDC half): `oidc_client_secret` and `oidc_client_secret_minio_hash` unset in dev, staging and prod. `make secrets-audit` exits 0 with no new orphan. `root_password` and `root_user` are PR 3.
- [ ] AC5: red on 2026-09-24. `pytest --runxfail tests/test_no_live_minio_references.py` fails with **93** live files, and lands as `xfail(strict=True)` (`6a6dbefb`).
- [x] AC6: `make backup-coverage ENV=prod`, 2026-09-26, after the prune: `beelink` covered, newest 00:03Z (0.3h); `rpi3` 22:02Z (2.3h); `rpi4` 23:59Z (0.4h); `vps` 00:02Z (0.3h). Every node covered, so nothing that ships to R2 depended on MinIO.

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
- **The Beelink teardown is ephemeral (operator, 2026-09-26).** The AC5 guard forbids any live file naming MinIO, and a teardown has to name what it removes. Exempting `beelink_services` from the guard would exempt exactly the file where a residual reference hides. So the teardown lands in PR 2, converges the only node that ever ran MinIO, and leaves in PR 3 with the SSOT block it reads, once AC2's `changed=0` run is recorded here. What makes it safe to delete is that nothing installs MinIO afterwards. The Ollama cleanup in the same role keeps its own, permanent policy; the two are not to be aligned.
- **The Headscale `tag:hermes → beelink:9000` grant goes in PR 2.** `tasks.md` named it as a comment to update, but the policy carries a live `accept` for that port. A grant to a retired port would pass to whatever binds it next without anyone deciding it.
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
