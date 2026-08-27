---
tags: [spec, tasks, templates]
created: "2026-08-27"
---

# Tasks - GITOPS-003

> TDD order. One task = one focused commit. Tick as you go. Reorder freely while spec is in `draft` state; freeze once you start `implementing`.
>
> **Inline markers**: `[P]` — no dependency on another unchecked task; `[AC<n>]` — helps satisfy acceptance criterion `<n>` in `proposal.md` (lets `/spec check` map coverage deterministically).
>
> **Shape**: five atomic PRs, each ≤300 LOC, in the order below. PR1 and PR2 are independent of the hook measurement; PR3 is not.

## Setup

- [ ] Branch created from master: `feat/gitops-003-argo-sync-smoke-test` (worktree `kubelab-gitops003-wt`)
- [x] `proposal.md` is complete and acceptance criteria are testable
- [x] Risk 1 resolved — measured 2026-08-27 from an ephemeral pod on `ace1`: both the hairpin and `traefik.kube-system.svc` reach the API; **decision: service + `--connect-to`** (recorded in `proposal.md`, Risks §1).
- [ ] Risk 2 resolved — PAT (fine-grained, `statuses:write` on kubelab, expiry set) vs GitHub App. Record the decision and the rotation path.
- [x] Risk 3 resolved — measured 2026-08-27: `timeout.reconciliation=120s`; merge→sync lag over 7 syncs = 0–6 min → **N = 10 min** (recorded in `proposal.md`).

## Implementation

### PR1 — Argo CD publishes a commit status per sync (AC1, AC5)

- [ ] [P] [AC5] Write failing test: render `trigger.on-sync-succeeded` / `on-sync-failed` with `operationState == nil` and with an empty `syncResult`; assert no expr-lang error and no false fire
- [ ] [AC5] Guard the trigger expressions so the test passes
- [ ] [AC1] Write failing test: `template.github-status-*` renders a `POST /repos/mlorentedev/kubelab/statuses/<revision>` body with `state`, `context: argocd/<app>`, `description` (≤140 chars, from `operationState.message`), `target_url`
- [ ] [AC1] Add `service.webhook.github` + the two templates + subscriptions to `infra/helm/argocd/values.yaml`; token placeholder in the SOPS-managed notifications secret (lesson-013: applied by `toolkit secrets apply`, never by Argo)
- [ ] [AC1] Apply on the hub (`make deploy-argocd` path), sync, and verify by consequence: `gh api repos/mlorentedev/kubelab/commits/<head>/status` shows `argocd/kubelab-staging`

### PR2 — `deploy-verify.yml` waits for the status (AC2)

- [ ] [P] [AC2] Write failing tests for `toolkit infra argo wait-status --sha --context --timeout`: `success` → 0; `failure` → non-zero with the description printed; no status after timeout → non-zero with "no status arrived" (GitHub API simulated)
- [ ] [AC2] Implement `wait-status` in `toolkit/features/argo_manager.py`
- [ ] [AC2] Add `.github/workflows/deploy-verify.yml`: `on: push` to `master`, paths `infra/k8s/overlays/{staging,prod}/**`, one job per touched env, timeout N; failure message links the runbook section (AC7)
- [ ] [AC2] Real runs recorded in `verification.md`: replay against `1489265` (red) and the next healthy merge (green)

### PR3 — `PostSync` hook probes the route (AC3) — blocked on Setup/Risk 1

- [ ] [AC3] Write failing generator test: the web app's overlay emits a `PostSync` Job with `hook-delete-policy: HookSucceeded`, sending a malformed `POST /api/subscribe` to the app's host via `traefik.kube-system.svc` (`--connect-to`), failing unless `400` + `text/plain`
- [ ] [AC3] Extend `toolkit/features/generator_k8s.py` + `infra/k8s/templates/` so the test passes; regenerate both overlays (drift gate stays clean)
- [ ] [AC3] Real run on staging recorded in `verification.md`: healthy → `Succeeded`, Job gone; forced failure (point the probe at `/`, which is nginx) → `Failed` + status `failure`

### PR4 — operator path (AC4, AC7)

- [ ] [P] [AC4] Write failing test for `toolkit infra argo verify-web --env`: exit 0 only on `Synced` at `origin/master` HEAD + `Succeeded` + `text/plain`; else non-zero printing `operationState.message`
- [ ] [AC4] Implement it; add `make verify-web ENV=staging|prod` (uses the ADR-052 kubeconfig)
- [ ] [AC7] Runbook section "deploy-verify is red": read the message → `make sync-app` → `make restart-argocd` only on a repeated panic; link it from lesson-407 and from the workflow failure message
- [ ] [AC4] Run `make verify-web` in both envs today; paste the output in `verification.md`

### PR5 — the token cannot expire silently (AC6)

- [ ] [P] [AC6] Write failing `tests/infra` check: the notifications token answers an authenticated `GET /rate_limit` with 200
- [ ] [AC6] Implement it (read the token via the same SOPS path as `secrets apply`; never print it)

## Closing

- [ ] Every acceptance criterion from `proposal.md` is covered by at least one test
- [ ] Every acceptance criterion has a matching entry in `features.json` with a non-vacuous verification command
- [ ] Type checks pass
- [ ] Lint passes
- [ ] No unrelated changes in the diff (no scope creep)
- [ ] `verification.md` filled in
- [ ] PRs opened referencing this spec folder; `adversarial-review` before `/spec archive`
