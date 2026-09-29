---
tags: [spec, verification, templates]
created: "2026-09-22"
---

# Verification - OPS-023-retire-minio

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 (K8s half, in the repo): `f798464b`. `kubectl kustomize` 2026-09-24: staging 96 objects, prod 99, with **0** MinIO and **0** `pvc-backup` references in either. Live before and after, per environment, are below. The SSOT half is PR 3a, under AC4 and the decisions.
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
  - **PR 3a (2026-09-28): the teardown leaves.** With the teardown, `beelink_minio_dir` and the three `minio_*` playbook vars removed, `make provision NODE=bee ENV=prod CHECK=1` from the branch: rc=0, `ok=104 changed=2 failed=0`. The two are `base_system : Update apt cache` and `docker : Download Docker GPG key`, both outside `beelink_services`; the role's compose file and unit report `ok`. Nothing reinstalls MinIO.
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
- [x] AC4 (OIDC half): `oidc_client_secret` and `oidc_client_secret_minio_hash` unset in dev, staging and prod. `make secrets-audit` exits 0 with no new orphan. `root_password` and `root_user` are PR 3.
  - **PR 3a (2026-09-28):** `toolkit secrets unset apps.services.data --env <env>` in dev, staging and prod. The subtree held only `minio.root_user` and `minio.root_password`, so the whole `data` key went. Same change: the `SECRET_CATALOG` entry, the `credentials generate` mint and its printout, `CREDENTIAL_SERVICE_MAP`, and the `root_user` line of `orphan-secrets-baseline.yaml` (the `uptime_kuma.admin_user` entry that compared itself to it now carries the reason itself). `make secrets-audit`, rc=0: dev 39/44, staging 57/57, prod 81/85, and no MinIO key among the orphans in any env. The missing keys are unrelated and pre-existing (the resume Drive secrets in prod, Vikunja and Gitea OIDC in dev).
- [x] AC5: red on 2026-09-24. `pytest --runxfail tests/test_no_live_minio_references.py` fails with **93** live files, and lands as `xfail(strict=True)` (`6a6dbefb`).
  - PR 3a left 22 live files, all of them docs. PR 3b, on 2026-09-28, rewrites 20 of them and marks two as `status: historical` with a banner, because each is a snapshot rather than a description of the present: `dash-001-homepage-cockpit.md`, the design record of a feature delivered on 2026-03-26, and `infra/dns-cloudflare.md`, a 2025-08-30 zone export. ADR-023, 028 and 061 D4 get a retirement note, not a rewrite. The `xfail` marker is removed, and `tests/test_no_live_minio_references.py` reports `13 passed`.
  - Mutation proof: with a WIP commit first, one appended `MinIO` line in `docs/runbooks/cicd.md` turns it red (`assert not ['docs/runbooks/cicd.md']`, `1 failed, 12 passed`). `git checkout HEAD --` puts it back to `13 passed`.
- [x] AC6: `make backup-coverage ENV=prod`, 2026-09-26, after the prune: `beelink` covered, newest 00:03Z (0.3h); `rpi3` 22:02Z (2.3h); `rpi4` 23:59Z (0.4h); `vps` 00:02Z (0.3h). Every node covered, so nothing that ships to R2 depended on MinIO.

## Test status

- Test suite: `make test` on 2026-09-24 -> `2645 passed, 15 skipped, 155 deselected, 1 xfailed` (the xfail is the AC5 guard).
- 2026-09-29, master `d7882172` after #1890: the AC5 guard `13 passed` with no xfail; the lesson index, spec gate and argo suites 189 passed.
- Manual smoke test: the live before/after reads above (both clusters, the Beelink, Authelia, DNS, Uptime Kuma, R2 coverage).
- No regressions in existing test suite: yes. CI green on #1880 and #1890 (#1890 merged unreviewed, disclosed on the PR: PR-Agent published no review in five attempts, TOOL-087 #1909).

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
- **PR 3 split in two (2026-09-28).** The sweep touches 72 files, about 45 of them docs. 3a carries everything that executes or is generated (Ansible, SSOT, SOPS, toolkit, tests, the dev stack, Makefile); 3b carries the docs, CLAUDE.md, README and the guard going green, with `Closes #972`. 3a stays green because the guard is still `xfail(strict=True)` and the docs still trip it.
- **`RETIRED_SECRETS` goes empty in 3a, by the same rule as the Beelink teardown.** Both envs read `minio-secrets` `NotFound` on 2026-09-26 and nothing renders it any more, so its entry leaves. The mechanism stays: its tests (`test_retired_secrets.py`, the preview tests in `test_apply_secrets_preview.py`) now patch in a synthetic entry, because an empty list makes every assertion over it vacuous. `test_secrets_orphan_audit.py` moved to a synthetic key too, as PR 1's task asked.
- **The K8s render did not move.** `kubectl kustomize` of both overlays at `origin/master` and on 3a: identical byte for byte, so removing the SSOT block rolls nothing in either cluster.
- **Found by the sweep:** the dev `mkcert` step copied the local CA root into the certs directory only for MinIO's container to trust; with MinIO gone that copy had no reader, so it went too. `SERVICES_DATA` went with its last member, and `generator_traefik.py`'s two MinIO special cases with it.
- **The guard exempts a file by its own frontmatter, not by a path list** (PR 3b). The four statuses are `historical`, `stale`, `superseded` and `absorbed`. A path list would have to be maintained by hand. A status is how the docs already mark a snapshot, and a file cannot claim it without saying so in a place a reviewer reads. A status written outside the frontmatter exempts nothing, and a test pins that.
- **The pattern is `(?<![a-z])minio`, not a substring and not `\bminio`** (PR 3b). The substring version matched the Spanish `dominio` in two docs. `\b` would miss `beelink_minio_dir`, because `_` is a word character. The lookbehind catches both, and parametrized cases pin each one.
- **Found by 3b's sweep, fixed here:**
  - `runbook-disaster-recovery.md` had two frontmatter blocks, and its restore step called an `ansible` `restore` playbook that does not exist. It now points to the restic restore in `offsite-backup-restore.md`.
  - The `backup.yml` usage comment named a `make backup-pvc-node` that was never wired.
  - CLAUDE.md's "PVC backup" gotcha still described the retired CronJob.
  - CLAUDE.md's `credentials generate` count (24 prod secrets and 2 hub secrets) was stale. Running the generator with its I/O mocked counts 19 keys to `prod.enc.yaml` and 4 to `common.enc.yaml`. The `secrets rotate` docstring now says "the Argo CD hub keys".
- **Found by 3b's sweep, ticketed:** `local-development.md` carried the real dev Gitea admin password, published since 2026-05-29. Checked by consequence (it matches dev SOPS; staging and prod do not). The literal is removed here, and the rotation is #1884 (SEC-023).
- **`docs/runbooks/pvc-backup-restore.md` was deleted in PR 1, not PR 3.** `test_runbook_targets_exist` fails on a runbook that names a removed `make` target.

## Review dispositions

Independent review, `review.md` (nan/mimo-v2.5, 2026-09-29, PASS WITH GAPS, minors only):

- **F1, VPNACL-001 still lists the MinIO grant as resolved:** applied. `specs/VPNACL-001-fleet-segmentation/proposal.md` gains a dated note: the target is gone and PR 2 removed the `accept`.
- **F2, AC5's exemption is broader than the proposal's wording** (the whole `specs/` tree and `docs/audits/`, not only archived specs): declined, recorded here. An active spec is where a retirement is planned, so it has to name what it retires, OPS-023's own folder included; `docs/audits/` holds dated snapshots. Both are documented in the guard's docstring. The contract is not edited under this verdict.
- **F3, ADR-061's Consequences still points at `overlays/prod/backup.yaml`:** applied, with a dated resolution note beside the bullet.
- **F4, the Argo CD values comment names `pvc-backup` CronJobs:** applied to the comment, not to the config. The review's premise that nothing renders a CronJob is wrong: `r2-backup-watcher`, `quota-watcher` and `disk-watcher` are CronJobs, so the health customization is still needed. The comment now names them.
- **F5, three functions in `k8s_secrets.py` at CC 16-21:** ticketed, DEBT-018 #1914. Partly pre-existing, partly grown across lanes; it is not in this spec's scope.
- **F6, #1890 merged without a review decision:** already disclosed on the PR and above; tracked by TOOL-087 #1909.
- **Unverified now:** staging and the Beelink were powered off during the review, so AC1-staging, AC2-live and AC3-staging rest on the timestamped captures above. Prod, the render, AC4, AC5 and AC6 were re-run fresh by the reviewer.

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes: docs/lessons/ci-automation/lesson-477-a-substring-guard-matches-another-languages-words.md (a substring guard fails on another language's words; a word boundary is wrong for identifiers, so use a letter lookbehind). PR 3a also produced docs/lessons/process-method/lesson-476-a-new-step-inside-a-piecemeal-mocked-function-runs-for-real-in-every-old-test.md.
- [x] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? No. ADR-061 D4 recorded the deferral, and its resolution note records the outcome.
- [x] New pattern candidate for `00_meta/patterns/`? No. Exempting a file through its own frontmatter is specific to this repo's docs lifecycle.

## Archive checklist

- [x] (✓ 2026-09-29) `proposal.md` frontmatter set to `status: archived`
- [x] (✓ 2026-09-29) Folder moved: `specs/OPS-023-retire-minio/` -> `specs/archive/OPS-023-retire-minio/`
- [x] (✓ 2026-09-29) Bitácora board ticket for this spec (#972) closed by the archive PR (ADR-018)
- [x] (✓ 2026-09-29) Promotions above executed: lessons 476 and 477, merged in #1880 and #1890
