---
tags: [spec, tasks, templates]
created: "2026-08-27"
---

# Tasks - GITOPS-003

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers**: `[P]` — no dependency on another unchecked task; `[AC<n>]` — helps satisfy acceptance criterion `<n>` in `proposal.md` (lets `/spec check` map coverage deterministically).
>
> **Shape**: five atomic PRs, each ≤300 LOC. **Order revised 2026-10-20 with the operator: PR4 first** (unblocked, offline-testable), then PR1 → PR2 once the PAT exists, PR3 once web#435 serves `commit` on staging, PR5 with PR1's token.

## Setup

- [x] ✓ 2026-10-20 Branch created from master: `feat/gitops-003-verify-staging` (worktree `worktrees/kubelab/feat-gitops-003-verify-staging`) for PR4
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] Risk 1 resolved — measured 2026-08-27 from an ephemeral pod on `ace1`: both the hairpin and `traefik.kube-system.svc` reach the API; **decision: service + `--connect-to`** (recorded in `proposal.md`, Risks §1).
- [x] ✓ 2026-08-28 Risk 2 resolved — fine-grained PAT (`statuses:write` on kubelab, expiry set), SOPS + `make apply-secrets ENV=prod`, no Argo CD restart (#1478 comment). Minting it is an operator step, still pending 2026-10-20.
- [x] Risk 3 resolved — measured 2026-08-27: `timeout.reconciliation=120s`; merge→sync lag over 7 syncs = 0–6 min → **N = 10 min** (recorded in `proposal.md`).

## Implementation

### PR1 — Argo CD publishes a commit status per sync (AC1, AC5)

- [x] ✓ 2026-08-22 [AC5] Nil guard and per-revision `oncePer` (`?.`, nil-safe for an empty `syncResult`) landed with #1276, held structurally by `tests/test_argocd_notification_triggers.py`
- [x] ✓ 2026-10-21 [AC1] Write failing test: `template.github-status-*` renders a `POST /repos/mlorentedev/kubelab/statuses/<revision>` body with `state`, `context: argocd/<app>`, `description` (≤140 chars, from `operationState.message`), `target_url`
- [x] ✓ 2026-10-21 [AC1] Add `service.webhook.github` + the two templates + subscriptions to `infra/helm/argocd/values.yaml`. The token (`argocd.github_status_token`, common SOPS) reaches the notifications secret the way the Slack webhook does, `make deploy-argocd`'s Helm `--set`, not `toolkit secrets apply` as first planned: that is the measured path for this secret
- [x] ✓ 2026-10-21 [AC2] Success keyed on the Synced `sync.revision`, not on the operation: a revision whose render is unchanged starts no operation, so it got no status and PR2's sweep would be red after nearly every merge (lesson-615). Failure stays on the operation's revision
- [ ] [AC1] Hub rebuild path: add `argocd.github_status_token` to Secret Manager (`sync_to_secret_manager`, `infra/terraform/gcp` secret ids, cloud-init `--set-file`, `tests/test_secret_manager_sync.py`). Until then a hub recreated from cloud-init posts no statuses, and `wait-status` reports "no status arrived"
- [x] ✓ 2026-10-22 [AC1] Apply on the hub (`make deploy-argocd` path), sync, and verify by consequence: `4c9cda6`, a no-op revision, got `argocd/kubelab-prod` and `argocd/kubelab-staging` success `Synced at 4c9cda6` (`verification.md`)

### PR2 — `deploy-verify.yml` waits for the status (AC2)

- [x] ✓ 2026-10-21 [P] [AC2] Write failing tests for `toolkit infra argo wait-status --sha --context --timeout`: `success` → 0; `failure` → non-zero with the description printed; no status after timeout → non-zero with "no status arrived" (GitHub API simulated)
- [x] ✓ 2026-10-21 [AC2] Implement `wait-status` in `toolkit/features/argo_manager.py` (`tests/test_argo_wait_status.py`, branch `feat/gitops-003-wait-status`)
- [x] ✓ 2026-10-21 [AC2] Add `.github/workflows/deploy-verify.yml`, one job per touched env, timeout N; failure message links the runbook section (AC7). **Trigger: NOT `on: push`.** Per Manu's decision on #1619 (2026-10-20) staging deploy PRs will be merged by a workflow, and a merge made with `GITHUB_TOKEN` starts no `on: push` workflow, so the check would silently never run after an unattended merge, the one case it is the compensating control for. Use `on: status` (the `argocd/kubelab-<env>` status Argo posts with its PAT does start workflows) plus a `schedule` sweep for the no-status case, or `workflow_run`; and a test asserting the trigger is not `push` alone. **Done as**: `status` (red on `failure`/`error` at once), a 30-min `schedule` sweep of master HEAD for **prod only** (staging is on-demand and repointable, so a missing staging status is not evidence; ADR-028), and `workflow_dispatch` replay; `tests/test_deploy_verify_workflow.py`. Merge after #2613 is live on the hub, or the first sweep is red on a no-op commit
- [x] ✓ 2026-10-22 [AC2] Real runs recorded in `verification.md`: replay against `1489265` (red) and the next healthy merge (green)

### PR3 — `PostSync` hook probes the route (AC3)

- [x] ✓ 2026-11-01 [AC3] Write failing generator test: the web app's overlay emits a `PostSync` Job with `hook-delete-policy: HookSucceeded`, sending a malformed `POST /api/subscribe` to the app's host via `traefik.kube-system.svc` (`--connect-to`), failing unless `400` + `text/plain`
- [x] ✓ 2026-11-01 [AC3] Extend `toolkit/features/generator_k8s.py` + `infra/k8s/templates/` so the test passes; regenerate both overlays (drift gate stays clean)
- [ ] [AC3] Real run on staging recorded in `verification.md`: healthy → `Succeeded`, Job gone; forced failure (point the probe at `/`, which is nginx) → `Failed` + status `failure`

### PR4 — operator path (AC4, AC7) — first, `feat/gitops-003-verify-staging`

- [x] ✓ 2026-10-20 [P] [AC4] Write failing tests `tests/test_product_verify.py`: the Application classification (Synced at HEAD + Succeeded → ready; a failed operation at HEAD → failed at once with its message; a sync revision behind HEAD → wait), the served-payload classification (`commit` match, mismatch, `"local"`, absent → not verifiable; semver against `version`), the pinned tag read from the rendered overlay, the host from the contract with in-tree/unregistered apps refused, and the loop's exit codes 0/1/2/3 against a fake clock
- [x] ✓ 2026-10-20 [AC4] Implement `toolkit/features/product_verify.py` + `toolkit infra argo verify-product --app --env --timeout`; add `make verify-product APP=<app> ENV=staging|prod` (hub kubeconfig, ADR-052)
- [x] ✓ 2026-10-20 [AC4] Run `make verify-product APP=web` in both envs; paste the output in `verification.md` (expected 2026-10-20: exit 3 in both, web#435 not shipped)
- [x] ✓ 2026-10-21 [AC7] Runbook section "deploy-verify is red" in `docs/runbooks/gitops-delivery-promotion.md`, linked from lesson-407 and from every failure annotation of `deploy-verify.yml`

### PR5 — the token cannot expire silently (AC6)

- [x] ✓ 2026-10-22 [P] [AC6] Write failing `tests/infra` check: the notifications token answers an authenticated GET with 200. **Done as** `GET /repos/mlorentedev/kubelab/commits/master/statuses`, not `/rate_limit`: `/rate_limit` answers 200 for any valid token, which says nothing about kubelab. The check proves validity and stated expiry only: kubelab is public, so the GET answers 200 for any valid token whatever it may write. The write grant is not verified; that probe is #2644
- [x] ✓ 2026-10-22 [AC6] Implement it (read the token via the same SOPS path as `secrets apply`; never print it): `tests/infra/test_argocd_status_token_live.py`, plus the stated expiry through `secret_expiry.github_pat_expiry`, the function `toolkit secrets check-expiry` already maps to this key

### PR6 — `delivery-watcher` bounds the no-status case (AC2, #2645 B)

- [x] ✓ 2026-10-31 [AC2] Record the sweep as measured: 40 `schedule` runs from 10-23 to 10-31, all green, 3 to 6 h apart (`verification.md`)
- [x] ✓ 2026-10-31 [P] [AC2] Write failing tests `tests/test_delivery_watcher.py` against the real `watch.py` with a simulated GitHub: `success` → `healthy: 1`; `failure`/`error` → 0 at any age; no status younger than N → 1, older → 0; the newest status of the context wins; GitHub unreachable or non-200 → a line with no `healthy`; exactly one line per run
- [x] ✓ 2026-10-31 [AC2] Implement `infra/k8s/base/services/delivery-watcher/watch.py` (stdlib only) and the CronJob (every 10 min, `backoffLimit: 0`, no token, non-root), its ingress-only NetworkPolicy, the image pin in `common.yaml`, and the prod patch of `ARGO_ENV`
- [x] ✓ 2026-10-31 [AC2] Grafana rule `gitops003-argo-delivery` in `grafana-alerting/delivery-rules.yaml`: `last_over_time(... unwrap healthy [30m]) by (namespace) < 1`, `for: 10m`, `noDataState: Alerting`, runbook `#deploy-verify-is-red`
- [x] ✓ 2026-10-31 [AC2] Validate in staging (Loki shows the line for master HEAD), then in prod after merge; record both in `verification.md`
- [ ] [AC2] See the red path live: a `healthy: 0` line and `gitops003-argo-delivery` firing in staging (master HEAD with no staging status, e.g. the slot repointed for over 10 minutes); record it in `verification.md`, then tick AC2
- [x] ✓ 2026-10-31 [AC2] Lesson: a GitHub `schedule` here is a few-times-a-day signal, not a cron

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PRs opened referencing this spec folder; `adversarial-review` before `/spec archive`
