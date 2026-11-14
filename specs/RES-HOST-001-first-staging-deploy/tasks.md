---
id: RES-HOST-001-first-staging-deploy
type: tasks
status: draft
created: "2026-11-13"
issue: "mlorentedev/kubelab#2366"
owner: manu
---

# RES-HOST-001 tasks

Order inside each slice: failing test, minimal code, refactor, then the slice's
mutation check (`make mutate FILE=<module> TEST=<test file>`) where it changes
Python. `[P]` marks a slice that can run in parallel with its neighbours.
`[ACn]` names the acceptance criterion a step proves.

**Who merges.** The owner merges anything touching `infra/`, `.github/workflows/`,
secrets, or a mint, and runs every deployed step. Otherwise the agent merges a
PR it opened under `.github/merge-grant.yml` (CI green, no conflicts,
`## Review triage` posted). Each slice is one PR of at most 300 changed lines,
excluding regenerated schema and snapshot files.

## Slices at a glance

| Slice | What | Size | Merges | Depends on |
|---|---|---|---|---|
| A | Sealed Secrets controller and SOPS key on staging, probe | ~250 | owner | none |
| K | ADR-073 to `accepted`, with the D9/D10 amendments | ~80 (docs) | owner | A deployed |
| B | Contract `resources:` (volume, job), `forwardauth-admins`, schema | ~200 | agent | K |
| C | Renderer: PVC, CronJob, mounts, fsGroup, Recreate, per-env schedule override | ~300 | owner | B |
| L | ADR-061 gate attributes generated claims by label | ~80 | agent | C |
| D [P] | `forwardauth-admins` render and Authelia subject test | ~100 | agent | B |
| E | Generated NetworkPolicy pair, egress profiles, n8n reciprocal | ~200 | owner | C, Q1, Q2 |
| F [P] | D8 hostname amendment | ~60 | agent | none |
| G | No-success alert rule and its `EXEMPT` entry | ~150 | owner | C, resume's success marker (G) |
| H | resume secrets: catalog entries and `resume-secrets` mapping | ~60 | owner (sets values) | none |
| I | resume onboarding (registry entry, snapshot, values, Authelia rule) | ~100 + data | owner | B to H, resume issue 810 shipped |
| J | First staging promote and runbook | ~120 (docs) | owner runs | I |

## A. Sealed Secrets key acceptance on staging (owner)

- [ ] A1 [AC8] Test: `cluster_bootstrap` has a `sealed-secrets` entry whose
  vendored manifest pins the image by digest and passes
  `--key-renew-period=0`.
- [ ] A2 [AC8] Vendor the controller to `infra/k8s/cluster/sealed-secrets/` and
  add the `cluster_bootstrap` entry in `common.yaml`.
- [ ] A3 [AC8] Test: `SecretMapping` accepts `labels` and `apply_secrets`
  renders them; existing mappings render unchanged. Add the field.
- [ ] A4 [AC8] Catalog entries for the key pair (`tls.crt`, `tls.key`) in SOPS,
  and a `SecretMapping` of type `kubernetes.io/tls` in the controller's
  namespace with label `sealedsecrets.bitnami.com/sealed-secrets-key=active`.
  The owner generates and sets the values; no value appears in the PR.
- [ ] A5 [AC8] Order: the runbook and the bootstrap target apply secrets before
  the controller, or the controller mints its own key. Test the order where a
  target encodes it.
- [ ] A6 [AC8] A probe `SealedSecret` sealed offline with `kubeseal --cert`
  against the SOPS cert, committed, with the expected sha256 of its plaintext.
  A verify command compares digests and prints only match or mismatch.
- [ ] A7 [AC8] Deployed (owner): apply, bootstrap, verify; run both again and
  record "unchanged". Record the evidence on #2449.

## K. ADR-073 acceptance record (owner, docs)

- [ ] Status to `accepted`, dated, citing step A7's evidence for D2.
- [ ] D9 note: `volume` backup is the node backup (`sqlite3 .backup`), not
  Litestream, for resume's subset.
- [ ] D10 note: restore verification and capacity admission deferred to the
  prod lane (Q8).

## B. Contract `resources:` (agent)

- [ ] B1 [AC1] Tests: v1 without `resources:` validates; volume plus job
  validates; refused with the field named: unknown `type`, unknown param,
  unknown `class`, bad name, `job.volume` not declared, `fs_group` out of
  range, non-absolute `mount_path`, invalid cron.
- [ ] B2 [AC1] Models: discriminated union on `type`, closed members, defaults
  (`class`, `active_deadline_seconds: 3600`). Cross-field check in
  `product_guards.py`.
- [ ] B3 [AC1] Test and literal: `auth: forwardauth-admins`.
- [ ] B4 [AC2] Regenerate `toolkit/schemas/kubelab-product.schema.json`;
  `tests/test_product_contract_schema.py` passes.
- [ ] B5 [AC3] `make validate-sync` passes with no generated diff.
- [ ] B6 Mutation check on `product_contract.py` and `product_guards.py`.

## C. Renderer (owner, touches `infra/k8s/templates/`)

- [ ] C1 [AC4] Tests on a fixture snapshot: one PVC `<app>-<name>`; one
  CronJob with Forbid, `backoffLimit: 2`, `activeDeadlineSeconds`,
  `restartPolicy: Never`, the app's image, ConfigMap, pull Secret and volume;
  the Deployment mounts the volume, sets `fsGroup` and
  `fsGroupChangePolicy: OnRootMismatch`, and uses `Recreate`. All carry
  `app.kubernetes.io/name: <app>`.
- [ ] C2 [AC4] Read claims from the env snapshot in `generator_k8s._build_context`;
  add the PVC and CronJob templates; branch the Deployment strategy on a mounted
  volume.
- [ ] C2b [AC4] Test, then code: a registry entry may carry
  `schedules: {<env>: {<job claim>: <cron>}}`; the renderer uses it over the
  contract's `schedule` for that env; an override naming an undeclared job or
  an invalid cron is refused. Platform-side, like `egress:`, so the contract
  keeps one schedule (Q6 mitigation).
- [ ] C3 [AC3] A product without `resources:` renders byte-identically
  (`make validate-sync`).
- [ ] C4 Mutation check on the claim-rendering functions.

## L. ADR-061 classification gate (agent)

- [ ] [AC5] Test: a generated claim with `app.kubernetes.io/name: resume` is
  attributed to `resume`, and its block resolves from `apps.platform.resume`.
- [ ] [AC5] Change `tests/test_stateful_service_classification.py` to attribute
  by label before falling back to the file stem.

## D. `forwardauth-admins` render (agent) [P]

- [ ] [AC7] Test: `product_render` maps it to `enable_auth: true`,
  `auth_level: one_factor` and group `admins`.
- [ ] [AC7] Test in `tests/test_authelia_access_rules.py`: every host of a
  `forwardauth-admins` product has a rule whose subject is exactly
  `group:admins` (vacuous until I).

## E. NetworkPolicy (owner)

- [ ] E1 [AC7] Tests: a product with `resources:` renders `<app>-ingress` (from
  Traefik on the port) and `<app>-egress` (the registry entry's profiles); a
  product without `resources:` renders none; an unknown profile name is refused.
- [ ] E2 [AC7] `egress:` on the registry entry schema; profiles `dns`,
  `public-https`, `notify` as in proposal D7.
- [ ] E3 [AC7] `n8n-ingress` gains a `from` for `app.kubernetes.io/name: resume`
  on 5678.
- [ ] E4 [AC7] `tests/test_networkpolicy_coverage.py` passes with the CronJob
  pods selected.
- [ ] E5 Rollback documented in the PR: delete `<app>-egress` if AC11
  over-blocks.

## F. D8 hostname amendment (agent) [P]

- [ ] [AC6] Tests in `tests/test_product_staging_hostname.py`, both halves:
  `resume.kubelab.live` pairs with `resume.staging.kubelab.live` and refuses
  `staging.resume.kubelab.live`; an own-domain prod still requires
  `staging.<domain>`; prod `kubelab.live` and prod `staging.kubelab.live` do not
  take the new rule; `hostnames.prod` without `events.prod` renders for staging.
- [ ] [AC6] Change `check_staging_hostname`; derive the apex from
  `WILDCARD_ZONE`.
- [ ] Dated note under ADR-067's D2 amendment and IDP-053 D8.
- [ ] Mutation check on `product_guards.py`.

## G. No-success alert (owner)

- [ ] G1 Read how `grafana-alerting` rule files reach Grafana (base
  `configMapGenerator` in `infra/k8s/base/kustomization.yaml`) and whether an
  overlay can add a file; place the rule so it does not fire in an env where
  resume does not run (staging overlay, or `noDataState: OK`).
- [ ] G2 [AC12] Test: the rule's window equals the effective schedule's
  period plus 2 hours in each env, where the effective schedule is the
  registry entry's override if set, else the snapshot's (26h for any daily
  schedule, for example `0 6 * * *`; 170h for a weekly staging override).
- [ ] G3 [AC12] The Loki rule on resume's success marker; an `EXEMPT` entry in
  `tests/test_alerting_emitter_window.py` with the owner's decision as reason;
  the job's container added to `CRONJOB_CONTAINERS` in
  `tests/test_alerting_unwrap_grouping.py`.

## H. resume secrets (owner sets values)

- [ ] Catalog `apps.platform.resume.llm_api_key`, one value shared by staging
  and prod (owner ruling Q6 = B; risk recorded in the proposal).
- [ ] `SecretMapping("resume-secrets")` with `RESUME_LLM_API_KEY` and the
  notify bearer (`apps.services.automation.notify.webhook_secret`).
- [ ] Test first: the generated `resume` ConfigMap carries no key whose
  source is in `SECRET_CATALOG`. `_extract_app_env_vars` keeps every
  `APPS_PLATFORM_RESUME_*` key and has no visible catalog filter
  (`toolkit/features/generator_k8s.py:363`), so a catalogued
  `apps.platform.resume.llm_api_key` could reach the ConfigMap in plaintext if
  decrypted values enter the flattened env. If the test fails, fix the filter
  in this slice and file the root cause.
- [ ] `toolkit secrets audit --env staging` reports both present.

## I. Onboarding (owner)

- [ ] Registry entry: forge gitea, `personal/resume`, receiver dormant,
  `events.staging` only, `image_registry: ghcr.io/mlorentedev`, `private: true`,
  `pull_credential: {username: mlorentedev, secret: ghcr.pull_token}`,
  `egress: [dns, public-https, notify]`, and the staging schedule override
  for the `daily` job at low frequency (for example weekly; Q6 mitigation).
- [ ] Contract snapshot for staging, with `hostnames.prod` declared and the
  volume claim named `data` (PVC `resume-data`, as proposal D11 assumes).
- [ ] Staging values: `resume_web_host: 0.0.0.0`, the public URL, the notify
  URL `http://n8n:5678/webhook/notify`, and the fixture seed setting that
  https://gitea.kubelab.live/personal/resume/issues/810 defines (Q5). That
  issue must ship in a published image before step J.
- [ ] ADR-061 classification entry.
- [ ] Staging Authelia rule with `subject: group:admins`.
- [ ] Portal tile and the e2e expectation for the new host.

## J. First staging deploy (owner runs)

- [ ] Runbook `docs/runbooks/runbook-resume-first-staging-deploy.md`: order
  (apply secrets, render, hand-run `toolkit deployment promote`), checks and
  rollback.
- [ ] [AC9] [AC10] [AC11] [AC12] Run, and record the evidence in
  `verification.md`.
