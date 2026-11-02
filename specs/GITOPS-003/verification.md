---
tags: [spec, verification, templates]
created: "2026-08-27"
---

# Verification - GITOPS-003

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 -> PR1 (#2594) and its amendment (#2613): live statuses below
- [x] AC2 -> PR2 (#2615): the `status` path and the red replay are live. PR6 (#2880, `ba9862a`): the in-cluster `delivery-watcher` bounds the no-status case (#2645 B); green in both envs, and red, firing and resolving in staging, all live below. Header drift in `deploy-verify.yml`: #2881
- [x] AC3 -> PR3 (#2899): `tests/test_k8s_generator_route_probe.py`; healthy, forced-failure and revert runs live in staging below
- [x] AC4 -> PR4 (#2579) and GITOPS-007 (#2584, `fix/gitops-007-superseded`): `tests/test_product_verify.py` (49 tests); live runs below
- [x] AC5 -> #1276, `tests/test_argocd_notification_triggers.py`
- [x] AC6 -> PR5: `tests/infra/test_argocd_status_token_live.py` proves the token still authenticates and has a future expiry; live run below. Not covered: the write grant (#2644)
- [x] AC7 -> PR2 (#2615): runbook section `deploy-verify is red`, linked from lesson-407 and every failure annotation; seen live in the red replay below

## Test status

- `poetry run pytest tests/test_product_verify.py -q --no-cov` → `49 passed`
- Mutation (`make mutate`): dropping `sync.revision == head` from the ready condition → 3 failed; treating a missing `commit` as present (`if False:`) → red. Both restored.
- Live, 2026-10-20, master `ed5747f`, from the workstation on the mesh:
  - `make verify-product APP=web ENV=staging TIMEOUT=45` → exit 3: `sync=Synced at ed5747f (HEAD ed5747f); last operation Succeeded at 4ab3083`, `serves no commit (version '1.16.0'), expected '7ebd808'`. Correct today: web#435 has not shipped.
  - `make verify-product APP=web ENV=prod TIMEOUT=45` → exit 0: `serves version '1.16.0', expected '1.16.0'`.
  - `make verify-product APP=api ENV=staging` → exit 2: `'api' has no product contract at ed5747f`.
- Live, 2026-10-21, master `49638d3`, after #2581 (staging web `sha-9d79e52`) merged and synced:
  - `make verify-product APP=web ENV=staging TIMEOUT=120` → exit 0: `sync=Synced at 49638d3 (HEAD 49638d3); last operation Succeeded at 49638d3`, `serves commit '9d79e52', expected '9d79e52'`, `VERIFIED`. AC4 holds end to end in staging (comment on #1478).
- Live, 2026-10-22, AC1 after #2613 (`4d16f35`) and `make deploy-argocd` from a checkout at master: master HEAD `4c9cda6` (#2624) touches no file under `infra/k8s/`, so it is a revision whose render is unchanged in both envs (the lesson-615 case).
  - `toolkit infra argo wait-status --sha 4c9cda64b8108163fe4cbaef58cd3f673e9ead13 --context argocd/kubelab-prod --timeout 300` → `SUCCESS: argocd/kubelab-prod is success: Synced at 4c9cda6`.
  - `gh api repos/mlorentedev/kubelab/commits/4c9cda64.../statuses`: `argocd/kubelab-prod success "Synced at 4c9cda6"` 06:42:49Z and `argocd/kubelab-staging success "Synced at 4c9cda6"` 06:42:50Z (new template), after `argocd/kubelab-prod success "successfully synced (all tasks run)"` 06:40:46Z from the old operation-keyed trigger, during the Authelia restart that `deploy-argocd` runs.
- Live, 2026-10-22, AC6, branch `feat/gitops-003-status-token-live`:
  - `poetry run pytest tests/infra/test_argocd_status_token_live.py -m infra --override-ini="addopts=" -q` → `2 passed`.
  - Mutation, by hand (the fixture returning a bogus `github_pat_` string, tree committed first, restored with `git checkout HEAD --`) → `2 failed`, neither skipped: a 401 fails with the rotation message and the expiry read raises `CredentialRejectedError`. `make mutate` could not run it: an `infra`-marked test is deselected by `pyproject` `addopts`, pytest exits 5 and the tool reports a red baseline (#2637).
  - Who runs it: nothing schedules `tests/infra` or `secrets check-expiry` (#1248). The loud signal for an expired token is `deploy-verify`'s prod sweep going red on "no status arrived" (#2615); this check names the cause.
- Live, 2026-10-22, AC2 after #2615 merged (`8582fe5`, 07:16Z):
  - `status` path: every Argo status since the merge started a green run, e.g. `8582fe5` (runs 39739407800, 39739409861), `681c30e`, `0a11015`. Statuses from other contexts start runs whose jobs are skipped, as the workflow header says.
  - `workflow_dispatch` replay of `1489265` (a commit that never got an Argo status), env staging, timeout 30 → run 39742730971 **failure**: `FAILED: no status arrived for argocd/kubelab-staging (deadline of 30s reached)`, then `##[error]Runbook: .../gitops-delivery-promotion.md#deploy-verify-is-red`.
  - Replay of `4c9cda6`, env prod → run 39742733932 **success**: `SUCCESS: argocd/kubelab-prod is success: Synced at 4c9cda6`.
  - Not yet seen: a `schedule` run. None by 08:07Z (the 07:37 and 08:07 slots), Not a one-off backlog: scheduled runs in this repository start 4 to 9.5 h late every day (delivery-health and config-drift, 10 days measured), so the sweep's latency is hours, not N. Tracked in #2645; AC2 stays open until it is decided and the first sweep is read.
- Read 2026-10-31, the sweep: `deploy-verify` `schedule` runs exist and are green, 40 of them from 2026-10-23T19:30Z to 2026-10-31T02:16Z, but 3 to 6 h apart instead of every 30 minutes (e.g. 18:49Z, 22:55Z, 02:16Z). Over the same week Argo posted `argocd/kubelab-prod` and `argocd/kubelab-staging` `success` on every master commit sampled (`38c1f081..9706719f`), each followed by green `status` runs. The sweep works, but only as a signal that arrives a few times a day; #2645 B (PR6) bounds the no-status case instead.
- Live, 2026-10-31, PR6 (#2880) in staging. Staging was pointed at `feat/gitops-003-delivery-watcher` from 04:50Z to 04:59Z (`make argo-set-revision`), then back to `master`.
  - `make watcher-run NAME=delivery-watcher ENV=staging` → `the Job succeeded in 17s`. This proves the pinned image, the non-root read-only pod with no token, and egress to GitHub under the NetworkPolicy.
  - Loki (`toolkit obs logs --env staging --service delivery-watcher`) holds the line: `{"metric": "argo_delivery", "argo_env": "staging", "sha": "e7ecfe4…", "age_seconds": 1791, "state": "success", "healthy": 1}`.
  - Grafana loaded `gitops003-argo-delivery` and evaluated it at 04:58:40Z: a Loki response with `framesLength=1`, and the rule not firing (`toolkit obs alerts --env staging`).
  - Not seen live: the red path. It is covered by `tests/test_delivery_watcher.py`. Prod is read after merge.
- Live, 2026-10-31, PR6 in prod after #2880 merged (`ba9862a`):
  - The first scheduled run is in Loki (`toolkit obs logs --env prod --service delivery-watcher`): `[06:30:04] {"metric": "argo_delivery", "argo_env": "prod", "sha": "f612c91…", "age_seconds": 325, "state": "success", "healthy": 1}`.
  - Runs at 06:40, 06:50, 07:00 and 07:10 printed the same `healthy: 1` line, each 10 minutes apart.
  - Grafana on `kubelab-vps` started evaluating `gitops003-argo-delivery` at 06:29:20Z (Loki responses), before the first line, so that first evaluation saw no data. At 07:18:16Z, `toolkit obs alerts --env prod` reports nothing firing or pending. With `noDataState: Alerting` and `for: 10m`, a rule that still read no data would be firing by then, so the rule reads the healthy series. That does not show it fires: the red path is still covered only by `tests/test_delivery_watcher.py`.

- Live, 2026-11-01, AC3 (#2899) in staging, slot pointed at `feat/gitops-003-postsync-probe` from 16:51Z:
  - Before: the hook's own request from the workstation, `POST /api/subscribe` with body `{`, answers `400 text/plain; charset=utf-8` on `mlorente.dev` and on `staging.mlorente.dev`. Prod gives the answer the probe requires before the probe ever runs there.
  - Healthy, `41a80dc`: the operation reached `Succeeded` at 16:52:30Z, with hook `Job web-route-probe-api PostSync Succeeded` (`status.operationState.syncResult.resources`). The Job is gone afterwards (`NotFound`, `HookSucceeded`), and the commit carries `argocd/kubelab-staging success`.
  - Forced failure, `01240c5` (probe path `/`): a commit that changes only the hook starts no operation and still gets `success "Synced at 01240c5"` (lesson-683, #2900). After `make sync-app`, the hook ended `Failed`. Loki: `route-probe: POST staging.mlorente.dev/ answered '405 text/html', expected '400 text/plain'`. The Application's `retry: {limit: 5}` re-ran the operation, and it ended `Failed` at 17:08:23Z. The commit then got `failure "one or more synchronization tasks completed unsuccessfully (retried 5 times)."` at 17:08:24Z.
  - Revert, `3e9f244`, after `make sync-app`: `Succeeded` at 17:17:17Z, hook `Succeeded`, status `success`.
- Live, 2026-11-01, AC2's red path in staging, during the same hold. Master moved while the slot pointed at the branch, so master HEAD `e23a080` (17:41Z) had no `argocd/kubelab-staging` status:
  - Watcher lines (`toolkit obs logs --env staging --service delivery-watcher`): 17:50 `healthy: 1` (age 508 s, inside the 600 s grace), 18:00 `state: null, healthy: 0` (age 1108 s), 18:10 `healthy: 0` (1709 s).
  - At 18:14:35Z, `toolkit obs alerts --env staging` showed `[FIRING] Argo CD has not applied master HEAD`.
  - The slot went back to master at 18:14:46Z. At 18:20 the watcher printed `state: "success", healthy: 1` for `e23a080`, again at 18:30, and at 18:40 the alert was no longer listed.
  - From merge to alert: 18:14 at the latest, for a 17:41 commit, so under 35 minutes against the previous 3-6 h sweep.

- Live, 2026-11-01, AC3 after #2899 merged (`2e84df1`): the first sync of each environment ran the hook. Prod: operation `Succeeded` at 19:39:37Z with `Job web-route-probe-api PostSync Succeeded`, and `argocd/kubelab-prod success "Synced at 2e84df1"`. Staging: `Succeeded` at 19:39:46Z, same hook result, `argocd/kubelab-staging success`.

- Live, 2026-10-31, AC2's no-data path, unplanned: staging's `gitops003-argo-delivery` fired at 06:09Z and resolved at about 06:38Z. The delivery watcher logged one line at 04:54Z and the next at 06:30Z, so the rule paged on a silent watcher, as AC2 says it must, not on a failed sync. Why staging's watcher was silent for 96 minutes is #1668's question (no data on an on-demand homelab).

## Independent pre-review, 2026-11-01 (PASS-WITH-GAPS)

A reviewer subagent that did not implement the spec read the contract and the PRs, ran every `features.json` command and 14 mutations (all red; the control stayed green), and read the hub. It found no Blocker. Dispositions:

- Major, THEORETICAL: "What" §3 promised a commit comparison in the hook. **Applied:** the descope is now declared in §3 (the commit check is AC4's).
- Major, THEORETICAL: AC6's test reads the SOPS copy of the token, not the one Argo holds. **Ticketed:** GITOPS-009 (#2918).
- Minor: AC5's test checks the expression text rather than evaluating it. **Declined:** three mutations of the nil and `oncePer` guards turned it red, so it is not vacuous. An expr-lang evaluator in the suite is not worth a dependency.
- Minor: `features.json` f2 omitted `tests/test_deploy_verify_workflow.py`, and f4 did not name exit 4. **Applied.** f1 reads only staging's `success` at run time. **Declined:** it is a live check by design.
- Minor: 48 vs 49 tests, and f3's first-prod-sync evidence was missing here. **Applied** (above).
- Minor, REAL: staging alerts route to the archive tier (`policies.yaml:19-21`), and the incidents behind this spec were staging ones. **Ticketed:** #1710 (Grafana routes by environment, not by severity). Until it lands, a failed staging sync still turns the post-merge `deploy-verify` run red on master's commit.
- Minor: the runbook's `make verify-product APP=<app>` works only for contract products. **Applied:** the step now says `APP=web`.
- Minor: AC2's "never as a broken deploy" read as "never alerts", but the rule alerts on no data. **Applied:** AC2 text.
- Speculative: `fetch_statuses` does not paginate past 100. **Declined:** a master commit carries a handful of contexts.

## Decisions made during implementation

- Product-agnostic, decided with the operator 2026-10-20: host and image from the contract snapshot, `/version.json` a platform convention; no contract schema change (IDP-042 untouched).
- "Synced at HEAD" is `sync.revision`, not the last operation's revision; Application health is not a condition (lesson-609).
- `commit` compared by strict equality with the tag minus `sha-`; a prefix match would accept a truncated answer.
- A missing `commit` keeps waiting until the deadline (an old pod may answer during a rollout), then exits 3.
- GITOPS-007 (#2584): HEAD is read once, so a merge synced during the poll used to make a landed promotion exit 1. A synced revision that descends from HEAD is now judged by the tag it pins: the same tag is judged at that revision; another tag is `SUPERSEDED`, exit 4, at once, never a pass under the new tag. Re-reading master each poll was rejected: it verifies "master now", not the promotion asked about.
- Application health stays out: the staging `Degraded` of 2026-10-20 is the `vikunja` Deployment (#1783), not retained watcher Jobs (#2580 misdiagnosed them, lesson-611).

## Promotion candidates

Before archiving, flag what (if anything) should be promoted to the vault. If all three are "no", archive in repo is the only persistence.

- [x] Lesson for the repo's `docs/lessons/`? yes: lesson-609 (Synced at HEAD is `sync.revision`), lesson-611 (an `appTree` Application cannot name its Degraded resource); lesson-407 already holds the incident
- [ ] ADR-worthy decision for the repo's `docs/adr/adr-XXX.md`? <yes / no - one line of what>
- [ ] New pattern candidate for `00_meta/patterns/`? Only if this recurs in >1 project. <yes / no - one line>

## Archive checklist

- [ ] `proposal.md` frontmatter set to `status: archived`
- [ ] Folder moved: `specs/GITOPS-003/` -> `specs/archive/GITOPS-003/`
- [ ] Bitácora board ticket for this spec moved to Done / closed with PR link (ADR-018)
- [ ] Promotions above executed (if any)
