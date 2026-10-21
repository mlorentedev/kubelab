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

### PR4 — operator path (AC4, AC7) — first, `feat/gitops-003-verify-staging`

- [ ] [P] [AC4] Write failing tests `tests/test_product_verify.py`: the Application classification (Synced at HEAD + Succeeded → ready; a failed operation at HEAD → failed at once with its message; a sync revision behind HEAD → wait), the served-payload classification (`commit` match, mismatch, `"local"`, absent → not verifiable; semver against `version`), the pinned tag read from the rendered overlay, the host from the contract with in-tree/unregistered apps refused, and the loop's exit codes 0/1/2/3 against a fake clock
- [ ] [AC4] Implement `toolkit/features/product_verify.py` + `toolkit infra argo verify-product --app --env --timeout`; add `make verify-product APP=<app> ENV=staging|prod` (hub kubeconfig, ADR-052)
- [ ] [AC4] Run `make verify-product APP=web` in both envs; paste the output in `verification.md` (expected 2026-10-20: exit 3 in both, web#435 not shipped)
- [ ] [AC7] Runbook section "deploy-verify is red" (moves to PR2, where the workflow that links it is born)

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
