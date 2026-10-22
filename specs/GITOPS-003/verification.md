---
tags: [spec, verification, templates]
created: "2026-08-27"
---

# Verification - GITOPS-003

## Evidence

Map every acceptance criterion from `proposal.md` to concrete proof (commit hash, test name, or observed behavior).

- [x] AC1 -> PR1 (#2594) and its amendment (#2613): live statuses below
- [ ] AC2 -> PR2
- [ ] AC3 -> PR3, after web#435 serves `commit` on staging
- [x] AC4 -> PR4 (#2579) and GITOPS-007 (#2584, `fix/gitops-007-superseded`): `tests/test_product_verify.py` (48 tests); live runs below
- [x] AC5 -> #1276, `tests/test_argocd_notification_triggers.py`
- [x] AC6 -> PR5: `tests/infra/test_argocd_status_token_live.py`; live run below
- [ ] AC7 -> PR2 (#2615): runbook section `deploy-verify is red`, linked from lesson-407 and every failure annotation

## Test status

- `poetry run pytest tests/test_product_verify.py -q --no-cov` → `48 passed`
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
